"""Tiny exact oracles for AGGREGATE_DP_V1 controls: brute-force enumeration of Z and every original singleton numerator in
exact rationals, and a seeded random generator of small adversarial models (nonbinary domains, arity >= 3, zeros,
constants, separable and bijection factors, duplicate scopes, evidence, disconnected components). Never used on the
benchmark path."""
from __future__ import annotations
import sys, random, itertools
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
from mdi import model as M
from adp import source as SRC


def brute(model, ev):
    """(Z, {v: [N_v(s) for s]}) over the ORIGINAL variables under evidence."""
    free = [v for v in range(model.nvars) if v not in ev]
    Z = Fr(0); N = {v: [Fr(0)] * model.card[v] for v in range(model.nvars)}
    strides = [f.strides() for f in model.factors]
    for states in itertools.product(*[range(model.card[v]) for v in free]):
        asg = dict(zip(free, states)); asg.update(ev); w = Fr(1)
        for f, st in zip(model.factors, strides):
            w *= f.table[sum(asg[v] * st[k] for k, v in enumerate(f.scope))]
            if w == 0:
                break
        if w == 0:
            continue
        Z += w
        for v in range(model.nvars):
            N[v][asg[v]] += w
    return Z, N


def brute_reduced(R):
    """(Z incl. scale, {v: {orig state: N}}) of a reduced model (adp.source.Reduced)."""
    vs = sorted(R.dom); Z = Fr(0); N = {v: {s: Fr(0) for s in R.dom[v]} for v in vs}
    for states in itertools.product(*[range(len(R.dom[v])) for v in vs]):
        pos = dict(zip(vs, states)); w = Fr(1)
        for f in R.factors:
            st = SRC.strides_of(f.card); w *= f.table[sum(pos[v] * st[k] for k, v in enumerate(f.scope))]
        Z += w
        for v in vs:
            N[v][R.dom[v][pos[v]]] += w
    return Z * R.scale, N


def marginals(model, ev):
    Z, N = brute(model, ev)
    if Z == 0:
        return Z, None
    return Z, {v: [x / Z for x in N[v]] for v in range(model.nvars)}


def gen(seed, nmax=6, kmax=3):
    rng = random.Random(seed); n = rng.randint(2, nmax)
    card = [rng.choice([2, 2, 3, 4]) for _ in range(n)]
    facs = []
    for j in range(rng.randint(1, n + 2)):
        k = rng.randint(1, min(kmax, n)); sc = tuple(rng.sample(range(n), k)); cd = tuple(card[v] for v in sc); size = SRC.prod(cd)
        mode = rng.random(); tab = []
        for i in range(size):
            if mode < 0.3:
                tab.append(Fr(rng.randint(1, 5), rng.randint(1, 3)))
            elif mode < 0.6:
                tab.append(Fr(0) if rng.random() < 0.4 else Fr(rng.randint(1, 5), rng.randint(1, 3)))
            else:
                tab.append(Fr(rng.randint(0, 3)))
        if k == 2 and cd[0] == cd[1] and rng.random() < 0.3:
            perm = list(range(cd[0])); rng.shuffle(perm); tab = [Fr(rng.randint(1, 3)) if perm[a] == b else Fr(0) for a in range(cd[0]) for b in range(cd[1])]
        if rng.random() < 0.12:
            tab = [Fr(2)] * size
        if k == 2 and rng.random() < 0.2:
            u = [Fr(rng.randint(0, 3)) for _ in range(cd[0])]; w = [Fr(rng.randint(1, 3)) for _ in range(cd[1])]; tab = [u[a] * w[b] for a in range(cd[0]) for b in range(cd[1])]
        if rng.random() < 0.1 and facs:                               # duplicate scope occurrence
            g = rng.choice(facs); sc, cd = g.scope, g.card; tab = [Fr(rng.randint(1, 4)) for _ in range(SRC.prod(cd))]
        facs.append(M.Factor(scope=sc, card=cd, table=tab, origin=j))
    ev = {}
    for v in range(n):
        if rng.random() < 0.2:
            ev[v] = rng.randrange(card[v])
    m = M.Model(nvars=n, card=card, factors=facs); m.validate()
    return m, ev


def write_uai(path, model, ev):
    with open(path, "w") as fh:
        fh.write("MARKOV\n%d\n%s\n%d\n" % (model.nvars, " ".join(map(str, model.card)), len(model.factors)))
        for f in model.factors:
            fh.write("%d %s\n" % (len(f.scope), " ".join(map(str, f.scope))))
        for f in model.factors:
            fh.write("%d\n%s\n" % (len(f.table), " ".join(_dec(x) for x in f.table)))
    with open(path + ".evid", "w") as fh:
        fh.write("%d %s\n" % (len(ev), " ".join("%d %d" % (v, s) for v, s in sorted(ev.items()))))


def _dec(q):
    """Exact finite decimal of a rational whose denominator divides a power of 10 after scaling -- generator values are
    small rationals; those with denominators 3 are written exactly by rescaling the WHOLE table? No: UAI needs decimals,
    so the generator writes num/den as a decimal with up to 30 digits only when exact; otherwise callers use in-memory models."""
    q = Fr(q)
    if q.denominator == 1:
        return str(q.numerator)
    den = q.denominator; k2 = 0; k5 = 0
    while den % 2 == 0:
        den //= 2; k2 += 1
    while den % 5 == 0:
        den //= 5; k5 += 1
    if den != 1:
        raise ValueError("not a finite decimal: %s" % q)
    k = max(k2, k5); scaled = q * 10 ** k
    s = str(scaled.numerator).rjust(k + 1, "0")
    return s[:-k] + "." + s[-k:]
