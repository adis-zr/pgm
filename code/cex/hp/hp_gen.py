"""Frozen twelve-input generator of the Hinton-to-Pearl compiler pilot (CLAUDE_TEST_PROMPT.md section 7). Deterministic: per-input seed = the first eight SHA-256 bytes (big-endian) of
'HINTON-PEARL-COMPILER-2026-11-23|<cycle16|grid4x4>|<8|16>|<exact|perturbed|generic>' feeding Python's random.Random (Mersenne Twister, documented); substreams for the permutations
derive from the same seed with suffix '|perm'. Inputs = topology {16-variable cycle, 4x4 nearest-neighbour grid} x fine cardinality {8, 16} x family {exact projective copies, weakly
perturbed copies, independent positive tables}. Structured families: two latent coarse states, d/2 copies each; coarse pair table from integers 1..9 (determinant-zero 2x2 rejected);
incidence scale 2^k, k uniform in -3..3 per (factor, axis, state); unary weights integers 1..9 over 8; fine entry = coarse entry x the two scales; perturbed: x (1 + sign / 16384), sign in {-1, +1}
per entry. Generic: pair entries integers 1..31 over 16, same unary rule. Every model is then permuted (variable ids, state labels per variable, factor order, factor axes); the
generative map is written separately and is NOT a planner input. Boundary / control fixtures live in check_hp.py, not here. usage: hp_gen.py OUTDIR [--tag TAG]"""
import sys, os, json, hashlib, random, itertools, argparse
from fractions import Fraction as F
TAG = 'HINTON-PEARL-COMPILER-2026-11-23'
TOPOLOGIES = ['cycle16', 'grid4x4']; CARDS = [8, 16]; FAMILIES = ['exact', 'perturbed', 'generic']

def seed_of(tag, topo, card, fam, suffix=''): return int.from_bytes(hashlib.sha256(('%s|%s|%d|%s%s' % (tag, topo, card, fam, suffix)).encode()).digest()[:8], 'big')

def edges(topo):
    if topo == 'cycle16': return [(i, (i + 1) % 16) for i in range(16)]
    e = []
    for r in range(4):
        for c in range(4):
            v = 4 * r + c
            if c + 1 < 4: e.append((v, v + 1))
            if r + 1 < 4: e.append((v, v + 4))
    return e

def build(tag, topo, card, fam):
    rng = random.Random(seed_of(tag, topo, card, fam)); n = 16; E = edges(topo); unary = [[F(rng.randrange(1, 10), 8) for _ in range(card)] for _ in range(n)]; facs = []; rec = dict(latent=None, coarse_tables=[], scales=[])
    if fam in ('exact', 'perturbed'):
        latent = [a // (card // 2) for a in range(card)]; rec['latent'] = latent           # before permutation: class = state // (d/2)
        for (u, v) in E:
            while True:
                T = [rng.randrange(1, 10) for _ in range(4)]
                if T[0] * T[3] - T[1] * T[2] != 0: break
            su = [F(2) ** rng.randrange(-3, 4) for _ in range(card)]; sv = [F(2) ** rng.randrange(-3, 4) for _ in range(card)]; vals = []
            for a in range(card):
                for b in range(card):
                    x = F(T[2 * latent[a] + latent[b]]) * su[a] * sv[b]
                    if fam == 'perturbed': x *= 1 + F(rng.choice((-1, 1)), 16384)
                    vals.append(x)
            facs.append(((u, v), vals)); rec['coarse_tables'].append(T); rec['scales'].append([[str(x) for x in su], [str(x) for x in sv]])
    else:
        for (u, v) in E: facs.append(((u, v), [F(rng.randrange(1, 32), 16) for _ in range(card * card)]))
    for v in range(n): facs.append(((v,), unary[v]))
    return dict(cards=[card] * n, factors=[dict(scope=sc, values=vals) for sc, vals in facs], evidence={}), rec

def permute(tag, topo, card, fam, m):
    rng = random.Random(seed_of(tag, topo, card, fam, '|perm')); n = len(m['cards']); new_of = list(range(n)); rng.shuffle(new_of)           # new_of[old] = new id
    smap = []
    for v in range(n):
        s = list(range(m['cards'][v])); rng.shuffle(s); smap.append(s)                                                                      # smap[old_var][old_state] = new state
    cards = [None] * n
    for old in range(n): cards[new_of[old]] = m['cards'][old]
    facs = []
    for f in m['factors']:
        sc = list(f['scope']); axes = list(range(len(sc))); rng.shuffle(axes); nsc = [new_of[sc[i]] for i in axes]; ocs = [m['cards'][v] for v in sc]
        old_strides = [1] * len(sc)
        for i in range(len(sc) - 2, -1, -1): old_strides[i] = old_strides[i + 1] * ocs[i + 1]
        inv = [None] * len(sc)
        for j, i in enumerate(axes): inv[i] = j                                                                                             # old axis i sits at new position inv[i]
        ncs = [cards[v] for v in nsc]; vals = [None] * len(f['values'])
        nst = [1] * len(sc)
        for i in range(len(sc) - 2, -1, -1): nst[i] = nst[i + 1] * ncs[i + 1]
        for x in itertools.product(*(range(c) for c in ocs)):
            idx_old = sum(old_strides[i] * x[i] for i in range(len(sc))); idx_new = sum(nst[inv[i]] * smap[sc[i]][x[i]] for i in range(len(sc))); vals[idx_new] = f['values'][idx_old]
        facs.append(dict(scope=tuple(nsc), values=vals))
    rng.shuffle(facs)
    return dict(cards=cards, factors=facs, evidence={}), dict(new_of_old=new_of, state_map_old=smap)

def write(path, m):
    lines = ['MARKOV', str(len(m['cards'])), ' '.join(map(str, m['cards'])), str(len(m['factors']))]
    for f in m['factors']: lines.append('%d %s' % (len(f['scope']), ' '.join(map(str, f['scope']))))
    for f in m['factors']: lines.append(str(len(f['values']))); lines.append(' '.join(str(x) for x in f['values']))
    open(path, 'w').write('\n'.join(lines) + '\n'); ev = m.get('evidence') or {}; open(path + '.evid', 'w').write(('%d ' % len(ev)) + ' '.join('%d %d' % kv for kv in sorted(ev.items())) + '\n')

def generate(outdir, tag=TAG):
    os.makedirs(outdir, exist_ok=True); man = []
    for topo in TOPOLOGIES:
        for card in CARDS:
            for fam in FAMILIES:
                m0, rec = build(tag, topo, card, fam); m, pi = permute(tag, topo, card, fam, m0); name = '%s_c%d_%s' % (topo, card, fam); p = os.path.join(outdir, name + '.uai'); write(p, m)
                json.dump(dict(name=name, tag=tag, seed=seed_of(tag, topo, card, fam), perm_seed=seed_of(tag, topo, card, fam, '|perm'), generative_record=rec, permutation=pi), open(os.path.join(outdir, name + '.generative_map.json'), 'w'), indent=1, default=str)
                man.append(dict(name=name, topology=topo, card=card, family=fam, nvars=16, nfactors=len(m['factors']), entries=sum(len(f['values']) for f in m['factors']), K=16 * card, model=os.path.abspath(p), evidence_file=os.path.abspath(p + '.evid'),
                                model_sha256=hashlib.sha256(open(p, 'rb').read()).hexdigest(), evid_sha256=hashlib.sha256(open(p + '.evid', 'rb').read()).hexdigest()))
    json.dump(dict(tag=tag, generator_sha256=hashlib.sha256(open(__file__, 'rb').read()).hexdigest(), inputs=man), open(os.path.join(outdir, 'GENERATED_MANIFEST.json'), 'w'), indent=1)
    return man

if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('outdir'); ap.add_argument('--tag', default=TAG); a = ap.parse_args()
    for m in generate(a.outdir, a.tag): print(m['name'], m['nfactors'], 'factors', m['entries'], 'entries', 'K', m['K'], m['model_sha256'][:12])
