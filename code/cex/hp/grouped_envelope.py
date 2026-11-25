"""DGP3 grouped-factor upper envelope (brief: DGP2 review 'next substantive experiment'; PROTOCOL.md section 1, lemma G). With the class map c(z) and the product decoder d(z|c) of an approximate stage FIXED,
replace the per-factor coarse maxima U_f(c_f) by JOINT maxima over bounded groups g of factors: U_g(c_{S_g}) = max_{z_{S_g} in the cell} prod_{f in g} h_f(z) with h_f the gauge residual (vals / prod lambda, exactly as
coarse_envelope.check_candidate computes it). Pointwise: prod_f h_f(z) <= prod_g U_g(c(z)) (each group's product at z is <= its cell maximum), and U_g <= prod_{f in g} U_f (a maximum of a product over compatible states
is <= the product of the maxima), so G_U^G(c) = prod_v A_v(c_v) prod_g U_g(c_{S_g}) is a valid upper model no looser than the per-factor one (G1). Grouping rule (frozen): level G1 = no grouping (the DGP2 envelope);
G2 = pairs of factors adjacent in factor order that SHARE a variable and whose joint scope has <= MAX_SCOPE variables and <= MAX_CELL fine states per coarse cell; G3 = triples likewise (a pair extended by the next
sharing factor). A factor that cannot be grouped under the caps stays alone (its per-factor U). Every group table is charged to the constructor budget before allocation and polled every 256 cells. Exact rationals.
Oracle control: lifted_decoder.enumerate_check with upper_fn verifies W'(z) <= G_U^G(c(z)) d(z|c(z)) on every fine state."""
import math, itertools
from fractions import Fraction as F
import numpy as np
import coarse_envelope as CE
MAX_SCOPE = 3; MAX_CELL_STATES = 64 ** 3


def plan_groups(M, Cz, level):
    """-> list of groups (tuples of factor indices) covering every factor exactly once, by the frozen rule; also the joint scopes"""
    n_f = len(M.factors); scopes = [tuple(sc) for sc, _ in M.factors]; groups = []; used = [False] * n_f; size = {'G1': 1, 'G2': 2, 'G3': 3}[level]
    def fits(idx):
        sc = sorted(set(v for i in idx for v in scopes[i])); cell = max((math.prod(M.cards[v] // 1 for v in sc), 1)); return len(sc) <= MAX_SCOPE and cell <= MAX_CELL_STATES
    for i in range(n_f):
        if used[i]: continue
        g = [i]; used[i] = True
        if size > 1:
            for j in range(i + 1, n_f):
                if len(g) >= size: break
                if used[j]: continue
                if set(scopes[j]) & set(v for k in g for v in scopes[k]) and fits(g + [j]): g.append(j); used[j] = True
        groups.append(tuple(g))
    return groups, [tuple(sorted(set(v for i in g for v in scopes[i]))) for g in groups]


def singleton_table_sorted(M, Cz, fi, S):
    """DGP4 R1: the per-factor upper table U_f of factor fi, TRANSPOSED from the factor's own axis order (M.factors[fi][0]) into the declared sorted scope S (row-major over Cz.ccards in S order).
    The DGP3 version copied Cz.U[fi] verbatim under the sorted scope: wrong semantics whenever the factor's scope is not already sorted (e.g. scope (1, 0))."""
    sc = tuple(M.factors[fi][0]); assert tuple(sorted(sc)) == tuple(S) and len(set(sc)) == len(sc), (sc, S)
    arr = np.array(Cz.U[fi], dtype=object).reshape([Cz.ccards[v] for v in sc]); perm = [sc.index(v) for v in S]
    return list(np.transpose(arr, perm).reshape(-1))


def grouped_upper_tables(M, classes, Cz, groups, gscopes, clock, budget):
    """for each group: the joint coarse scope (variables, sorted), the coarse cell table U_g (exact Fractions, row-major over the coarse cards of the SORTED scope); charged before allocation, polled every 256 fine
    states. DGP4 R2: this function OWNS its live charge until it returns it to the caller (exactly once); on ANY failure (MEMORY / DEADLINE / defect) every byte it charged is released before the exception
    propagates (the DGP3 version left the admitted tables' bytes orphaned in the constructor account: 2,800 B after a MEMORY refusal on the second table, 8,400 B after a DEADLINE in the third)."""
    owned = [0]
    try: return _grouped_upper_tables(M, classes, Cz, groups, gscopes, clock, budget, owned)
    except BaseException:
        if owned[0]: budget.release(owned[0]); owned[0] = 0
        raise


def _grouped_upper_tables(M, classes, Cz, groups, gscopes, clock, budget, owned):
    scales = Cz.scales; tables = []
    for gi, (g, S) in enumerate(zip(groups, gscopes)):
        ccs = [Cz.ccards[v] for v in S]; vol = math.prod(ccs); fine_vol = math.prod(M.cards[v] for v in S)
        owned[0] += budget.charge(2 * (56 + (8 + CE.FRAC_BYTES) * vol) + 64 * vol, 'grouped upper table of group %d (%d cells)' % (gi, vol)); clock.poll('before grouped table %d' % gi)
        if len(g) == 1:
            fi = g[0]; tables.append((S, singleton_table_sorted(M, Cz, fi, S))); continue      # ungrouped factor: the per-factor U in the SORTED scope order (R1)
        cst = CE.strides(ccs); U = [None] * vol; pos = {v: k for k, v in enumerate(S)}
        facs = [(fi, tuple(M.factors[fi][0]), M.factors[fi][1], CE.strides([M.cards[v] for v in M.factors[fi][0]])) for fi in g]
        for idx, x in enumerate(itertools.product(*(range(M.cards[v]) for v in S))):
            h = F(1)
            for fi, sc, vals, fst in facs:
                fidx = sum(fst[ax] * x[pos[v]] for ax, v in enumerate(sc)); e = vals[fidx]
                if e == 0: h = F(0); break
                for ax, v in enumerate(sc): e = CE.checked_div(e, scales[(fi, ax)][x[pos[v]]])
                h = CE.checked_mul(h, e)
            c = sum(cst[k] * classes[v][x[k]] for k, v in enumerate(S))
            if U[c] is None or h > U[c]: U[c] = h
            if (idx & 255) == 255: clock.poll('in grouped table %d' % gi)
        tables.append((S, U))
    charged = owned[0]; owned[0] = 0                                                              # ownership transfers to the caller exactly once (the except-path above no longer sees it)
    return tables, charged


def grouped_coarse_model(M, Cz, tables):
    """the executor-shaped upper coarse model: singleton A_v factors + one factor per group over its joint coarse scope (the scalar stays outside, as in coarse_envelope.coarse_model)"""
    return dict(cards=list(Cz.ccards), evidence={}, factors=[dict(scope=(v,), values=list(Cz.A[v])) for v in range(len(Cz.ccards))] + [dict(scope=tuple(S), values=list(U)) for S, U in tables])


def grouped_upper_weight(M, Cz, tables):
    """exact G_U^G(c) = scalar prod A prod U_g (oracle / controls)"""
    def fn(c):
        w = M.scalar
        for v, cc in enumerate(c): w *= Cz.A[v][cc]
        for S, U in tables:
            idx = 0
            for v in S: idx = idx * Cz.ccards[v] + c[v]
            w *= U[idx]
        return w
    return fn


def check_dominance(M, Cz, tables, groups):
    """lemma G, second part: U_g <= prod_{f in g} U_f on every coarse cell of every grouped table (cheap, exact; controls)"""
    for (S, U), g in zip(tables, groups):
        if len(g) == 1: continue
        ccs = [Cz.ccards[v] for v in S]; pos = {v: k for k, v in enumerate(S)}
        for idx, c in enumerate(itertools.product(*(range(k) for k in ccs))):
            prod = F(1)
            for fi in g:
                sc = tuple(M.factors[fi][0]); cst = CE.strides([Cz.ccards[v] for v in sc]); prod *= Cz.U[fi][sum(cst[ax] * c[pos[v]] for ax, v in enumerate(sc))]
            if U[idx] > prod: raise CE.Defect('grouped U exceeds the product of per-factor U on cell %s' % (c,))
    return True
