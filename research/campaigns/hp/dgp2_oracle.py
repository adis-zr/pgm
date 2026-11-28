"""DGP2 oracle harness (brief sections 2-4): exact enumeration of small dense models, the stream laws ACTUALLY specified by the samplers (original = block / mini-bucket PAC on the separator space after contraction;
lifted = coarse mini-bucket law x dyadic decoder rows), the importance quantities R*, M2, V_j in one unit convention, the cap decomposition C / Z = (B / Z_U)(Z_U / Z) K_hi, the fixed-r limits M2_min^(r) and R*_min^(r)
with their attaining laws, the exact-upper coarse law q_U, and paired reference replays (seeds 1-3, 2^18 draws, checkpoints 2^10..2^18, treatments A-D on identical draws). ORACLE ONLY: never a planner arm.
Forced-PAC diagnostic profile (frozen for the oracle panel only): table_cap 16, enum_cap 1, mb_cap 16, exact_route False, batch 1024, targeted schedule.
usage: dgp2_oracle.py MODEL.uai OUT.json [--cap-s 100] [--replay-draws 262144] [--seeds 1,2,3] [--no-replay]"""

# Source-checkout entry point; production imports never traverse research.
if __package__ in (None, ""):
    import sys as _research_sys
    from pathlib import Path as _ResearchPath
    _research_sys.path.insert(0, str(_ResearchPath(__file__).resolve().parents[3]))
from research.bootstrap import activate as _activate_research
_activate_research()
from research.paths import repo_root as _repo_root, runs_root as _runs_root, records_root as _records_root, source_path as _source_path
import sys, os, json, time, math, argparse, itertools, hashlib
from fractions import Fraction as F
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
import pgm.algorithms.quotient.coarse_envelope as CE, pgm.algorithms.quotient.pac_actions as PA, pgm.algorithms.quotient.lifted_decoder as LD, pgm.algorithms.block.integrated as IG, pgm.algorithms.structural.core as CORE
PROFILE = dict(table_cap=16, enum_cap=1, mb_cap=16, batch=1024, schedule='targeted', crosscheck=True, exact_route=False)
EPS = F(1, 200); DELTA = F(1, 10 ** 6); CHECKPOINTS = [1 << 10, 1 << 12, 1 << 14, 1 << 16, 1 << 18]
tnow = time.monotonic


class Deadline(Exception): pass


def fl(q): return float(q) if (q.numerator.bit_length() < 1000 and q.denominator.bit_length() < 1000) else math.ldexp(float(q / F(2) ** (q.numerator.bit_length() - q.denominator.bit_length())), q.numerator.bit_length() - q.denominator.bit_length())
def lg(q): return (math.log2(q.numerator) - math.log2(q.denominator)) if q > 0 else -math.inf
def sqrt_up(q):
    """outward (upper) rational square root on the 2^-60 grid"""
    if q == 0: return F(0)
    n = q.numerator << 120; d = q.denominator; r = math.isqrt(n // d) + 1; return F(r, 1 << 60)
def sqrt_dn(q):
    if q == 0: return F(0)
    n = q.numerator << 120; d = q.denominator; r = math.isqrt(n // d); return F(r, 1 << 60)


# ---------------------------------------------------------------- exact enumeration of the original target
def enumerate_original(M, deadline):
    """canonical model M (coarse_envelope.Canon): W(z) for every fine state (Fractions, scalar INCLUDED), Z, singleton marginals on ORIGINAL coordinates"""
    cards = list(M.cards); n = len(cards); states = list(itertools.product(*[range(k) for k in cards])); W = []; Z = F(0); num = {}
    for i, z in enumerate(states):
        if (i & 1023) == 1023 and tnow() >= deadline: raise Deadline('enumeration')
        w = LD.parent_weight(M, z); W.append(w); Z += w
        for v, a in enumerate(z): num[(v, a)] = num.get((v, a), F(0)) + w
    mu = {(int(M.orig_of[v]), a): num[(v, a)] / Z for (v, a) in num} if Z > 0 else {}
    return dict(states=states, W=W, Z=Z, mu=mu, mu_canon={k: num[k] / Z for k in num} if Z > 0 else {})


# ---------------------------------------------------------------- the ORIGINAL stream's law and effective target on the separator space
def original_stream(st, seed, deadline):
    S = PA.Stream(1, 'original', st.model, st.queries, seed, EPS, DELTA / 2, dict(PROFILE)); r = S.prepare(deadline, cdead=deadline); return S, r


def original_quantities(S, enum, M, deadline):
    """effective target W_s(s) = sum_{z: sep(z) = s} W(z) (EXACT), responses g_j(s) = sum W(z) 1[z_j] / W_s(s) (Rao-Blackwellized; indicator for separator coordinates; DOUBLE precision with relative error <= 2 n_states u),
    analyzed law q(s) from the sampler's exact replay (logq_given, EXACT), the implemented cap in W_int units, R*, M2, C_tight (EXACT), V_j and Var_p[g_j] (double)"""
    cards = S.cards; sep = list(S.S); pos = S.pos; n = len(cards); K = S.Kq; sq = S.sq; nst = len(enum['states'])
    sidx = {}; sstates = []; agg = []; 
    for z, w in zip(enum['states'], enum['W']):
        key = tuple(z[v] for v in sep); i = sidx.get(key)
        if i is None: i = len(sstates); sidx[key] = i; sstates.append(key); agg.append(F(0))
        agg[i] += w
    Zs = sum(agg); E = max(1, max(w.numerator.bit_length() - w.denominator.bit_length() for w in enum['W'] if w > 0)) - 60
    wf = np.array([float(w / F(2) ** E) if w > 0 else 0.0 for w in enum['W']]); aggf = np.zeros(len(sstates)); G = np.zeros((len(sstates), K)); srow = np.array([sidx[tuple(z[v] for v in sep)] for z in enum['states']], dtype=np.int64)
    np.add.at(aggf, srow, wf)
    Zarr = np.array(enum['states'], dtype=np.int64)
    for j, (x, a) in enumerate(sq): np.add.at(G[:, j], srow, wf * (Zarr[:, x] == a))
    with np.errstate(invalid='ignore', divide='ignore'): G = np.where(aggf[:, None] > 0, G / np.where(aggf > 0, aggf, 1.0)[:, None], 0.0)
    Sb = np.zeros((len(sstates), len(pos)), dtype=np.int64)
    for k, v in enumerate(sep): Sb[:, pos[v]] = np.array([s_[k] for s_ in sstates], dtype=np.int64)
    q_an = []
    for i in range(0, len(sstates), 4096):
        if tnow() >= deadline: raise Deadline('analyzed law')
        lq, qa = S.mbp.logq_given(Sb[i:i + 4096], pos); q_an += qa
    tot_q = sum(q_an); omitted = sum(agg[i] for i, q in enumerate(q_an) if q == 0)
    flat = [np.asarray(b.arr, dtype=object).reshape(-1).tolist() for b in S.live_blocks]; scopes = [b.scope for b in S.live_blocks]
    Wint = []
    for s_ in sstates:
        w = 1
        for fb, sc in zip(flat, scopes):
            idx = 0
            for x in sc: idx = idx * cards[x] + s_[sep.index(x)]
            w *= int(fb[idx])
        Wint.append(F(w))
    Zint = sum(Wint); ratio_units = (Zint / Zs) if Zs > 0 else None
    C_int = F(2) ** int(math.floor(S.logU_capf)) * F(2.0 ** (S.logU_capf - math.floor(S.logU_capf))) * F(2) ** S.mbp.E_U
    Rstar = F(0); M2 = F(0); Ctight = F(0); Xmax_impl = F(0); support_fail = False
    for i, q in enumerate(q_an):
        if (i & 4095) == 4095 and tnow() >= deadline: raise Deadline('moments')
        if q == 0:
            if agg[i] > 0: support_fail = True
            continue
        p = agg[i] / Zs; Rstar = max(Rstar, p / q); M2 += p * p / q; Ctight = max(Ctight, Wint[i] / q); Xmax_impl = max(Xmax_impl, Wint[i] / (C_int * q))
    pf = aggf / aggf.sum(); qf = np.array([fl(q) for q in q_an]); mu = (pf[:, None] * G).sum(axis=0)
    with np.errstate(divide='ignore', invalid='ignore'): wq = np.where(qf > 0, pf * pf / np.where(qf > 0, qf, 1.0), 0.0)
    Vj = (wq[:, None] * (G - mu[None, :]) ** 2).sum(axis=0); varp = (pf[:, None] * (G - mu[None, :]) ** 2).sum(axis=0)
    out = dict(kind='original', separator_vars=len(sep), eliminated_vars=len(S.order), n_sep_states=len(sstates), n_fine_states=nst, Z_effective=str(Zs), Z_int=str(Zint), units_ratio_Wint_over_Ws=str(ratio_units), total_q=str(tot_q), support_failure=support_fail, omitted_target_mass_fraction=(fl(omitted / Zs) if Zs > 0 else None),
               R_star=fl(Rstar), M2=fl(M2), log2_R_star=lg(Rstar), log2_M2=lg(M2), C_over_Z=fl(C_int / Zint), log2_C_over_Z=lg(C_int / Zint), C_tight_over_Z=fl(Ctight / Zint), log2_C_tight_over_Z=lg(Ctight / Zint), cap_ratio_impl_over_tight=fl(C_int / Ctight) if Ctight > 0 else None, max_X_analyzed=fl(Xmax_impl), ordering_ok=bool(1 <= M2 <= Rstar <= C_int / Zint + F(1, 10 ** 12)),
               V_j=[float(x) for x in Vj], var_p_g_j=[float(x) for x in varp], second_moment_precision='double (relative error <= 2 n_states u on each sum; the exact quantities are Z, W_s, q, R*, M2, C_tight)', constant_responses=[int(j) for j in range(K) if varp[j] < 1e-300], mu_j=[float(x) for x in mu], K=K, queries=[list(q) for q in sq], mb_splits=S.mbp.splits, mb_cap=S.cap_used, eps_num=S.eps_num, alpha=S.alpha, logU_capf=S.logU_capf, E_U=S.mbp.E_U, E_tot=S.E_tot,
               dense_blocks=S.dense_blocks, shared_blocks=S.shared_blocks)
    tables = dict(sstates=sstates, q_an=q_an, Wint=Wint, C_int=C_int, Ctight=Ctight, G=G, mu=mu, Zint=Zint, K=K, sep=sep, pos=pos, cards=cards)
    return out, tables


def flat_index(scope, s, sep, cards):
    idx = 0
    for x in scope: idx = idx * cards[x] + s[sep.index(x)]
    return idx
def pos_of(sep, x, s): return sep.index(x)


# ---------------------------------------------------------------- the LIFTED stream's law: coarse mini-bucket law x dyadic rows; decomposition; fixed-r limits; exact-upper law
def lifted_stream(M, seed, deadline, budget):
    clk = CE.Clock(deadline, {}); prof, why = CE.slice_profiles(M, clk, budget)
    if prof is None: return None, 'PROPOSER: ' + str(why), None, None
    classes = [CE.canonical_classes(CE.farthest_split(prof[v], list(range(M.cards[v])), clk), M.cards[v]) for v in range(len(M.cards))]; Cz = CE.check_candidate(M, classes, CE.unit_scales(M), clk, budget, ratio_product='compact')
    S = PA.LiftedStream(2, M, M, [], classes, Cz, seed, EPS, DELTA / 4, dict(PROFILE, budget_obj=budget)); r = S.prepare(deadline); return S, r, classes, Cz


def lifted_quantities(S, classes, Cz, enum, M, deadline, cache=None):
    n = len(M.cards); cards = list(M.cards); Z = enum['Z']; identity_map = all(len(set(cl)) == len(cl) for cl in classes); states = enum['states']; Wl = enum['W']
    cstates = list(itertools.product(*[range(k) for k in Cz.ccards])); Sb = np.array(cstates, dtype=np.int64); lq, q_C = S.mbp.logq_given(Sb, S.pos); qC = dict(zip(cstates, q_C))
    ufn = S.upper_weight_fn() if hasattr(S, 'upper_weight_fn') else (lambda c: LD.upper_weight(M, Cz, c)); G_U = {c: ufn(c) for c in cstates}; Z_U = sum(G_U.values())      # DGP3: the stream's OWN upper model (grouped when envelope != G1)
    B_int = F(2) ** int(math.floor(S.mbp.logU_f)) * F(2.0 ** (S.mbp.logU_f - math.floor(S.mbp.logU_f))) * F(2) ** S.mbp.E_U * (1 + F(S.mech['rho_cap'])); B_viol = sum(1 for c in cstates if qC[c] > 0 and F(S.scale_C) * G_U[c] > B_int * qC[c])
    K_hi = S.rows.K.hi(); K_lo = S.rows.K.lo(); kappa_exact = LD.exact_kappa(S.rows)
    C_int = F(2) ** int(math.floor(S.logU_capf)) * F(2.0 ** (S.logU_capf - math.floor(S.logU_capf))) * F(2) ** S.mbp.E_U; Zint = F(S.scale_F) * Z / M.scalar
    C_over_Z = C_int / Zint; B_over_ZU = B_int / (F(S.scale_C) * Z_U); ZU_over_Z = Z_U / (Z / M.scalar); decomposition = B_over_ZU * ZU_over_Z * K_hi; numerical_inflation = C_over_Z / decomposition
    cmap = [tuple(classes[v][z[v]] for v in range(n)) for z in states]; Tc = {}
    for c, w in zip(cmap, Wl): Tc[c] = Tc.get(c, F(0)) + w
    rprob = [[{a: LD.r_prob(S.rows, v, c, a) for a in S.rows.members[v][c]} for c in range(Cz.ccards[v])] for v in range(n)]
    cached = cache is not None and 'rvals' in cache; Hc = dict(cache['Hc']) if cached else {}; tc = dict(cache['tc']) if cached else {}; Rstar = F(0); M2 = F(0); Ctight = F(0); Xmax = F(0); support_fail = False; omitted = F(0); rvals = cache['rvals'] if cached else []
    for i, (z, w, c) in enumerate(zip(states, Wl, cmap)):
        if (i & 4095) == 4095 and tnow() >= deadline: raise Deadline('lifted moments')
        if cached: r_ = rvals[i]
        else:
            r_ = F(1)
            for v in range(n): r_ *= rprob[v][c[v]][z[v]]
            rvals.append(r_)
            if Tc[c] > 0 and r_ > 0 and w > 0: pzc = w / Tc[c]; Hc[c] = Hc.get(c, F(0)) + pzc * pzc / r_; tc[c] = max(tc.get(c, F(0)), w / r_)
        q = qC[c] * r_
        if q == 0:
            if w > 0: support_fail = True; omitted += w
            continue
        p = w / Z; Rstar = max(Rstar, p / q); M2 += p * p / q; Ctight = max(Ctight, F(S.scale_F) * (w / M.scalar) / q); Xmax = max(Xmax, F(S.scale_F) * (w / M.scalar) / (C_int * q))
    if cache is not None and not cached: cache.update(rvals=rvals, Hc=Hc, tc=tc)                   # DGP3: r-only quantities shared across envelope levels (the decoder r is the same stream-independent object)
    pC = {c: Tc[c] / Z for c in Tc}; M2_lift = sum(pC[c] ** 2 * Hc[c] / qC[c] for c in Hc if qC[c] > 0); M2_coarse = sum(pC[c] ** 2 / qC[c] for c in Tc if qC[c] > 0)
    M2_min = sum(pC[c] * sqrt_up(Hc[c]) for c in Hc) ** 2; M2_min_lo = sum(pC[c] * sqrt_dn(Hc[c]) for c in Hc) ** 2; Rstar_min = sum(tc.values()) / Z
    wsum = sum(pC[c] * sqrt_up(Hc[c]) for c in Hc); q_m2 = {c: pC[c] * sqrt_up(Hc[c]) / wsum for c in Hc}; M2_at_qm2 = sum(pC[c] ** 2 * Hc[c] / q_m2[c] for c in Hc if q_m2[c] > 0)
    tsum = sum(tc.values()); q_r = {c: tc[c] / tsum for c in tc}; Rstar_at_qr = max(((w / Z) / (q_r[c] * r_)) for w, c, r_ in zip(Wl, cmap, rvals) if w > 0 and c in q_r and r_ > 0)
    qU = {c: G_U[c] / Z_U for c in cstates}; RU = F(0); M2U = F(0); CU = F(0)
    for w, c, r_ in zip(Wl, cmap, rvals):
        q = qU[c] * r_
        if q > 0 and w > 0: RU = max(RU, (w / Z) / q); M2U += (w / Z) ** 2 / q; CU = max(CU, w / q)
    # responses (fine indicators) and second moments in double
    E = max(1, max(w.numerator.bit_length() - w.denominator.bit_length() for w in Wl if w > 0)) - 60; pf = np.array([float(w / F(2) ** E) if w > 0 else 0.0 for w in Wl]); pf = pf / pf.sum(); qf = np.array([fl(qC[c] * r_) for c, r_ in zip(cmap, rvals)])
    Zarr = np.array(states, dtype=np.int64); K = S.Kq; G = np.zeros((len(states), K))
    for j, (v, a) in enumerate(S.queries): G[:, j] = (Zarr[:, v] == a).astype(float)
    mu = (pf[:, None] * G).sum(axis=0)
    with np.errstate(divide='ignore', invalid='ignore'): wq = np.where(qf > 0, pf * pf / np.where(qf > 0, qf, 1.0), 0.0)
    Vj = (wq[:, None] * (G - mu[None, :]) ** 2).sum(axis=0); varp = (pf[:, None] * (G - mu[None, :]) ** 2).sum(axis=0)
    hc_mass = sorted([(fl(pC[c]), fl(Hc.get(c, F(0))), (fl(pC[c] ** 2 * Hc.get(c, F(0)) / qC[c]) if qC[c] > 0 else None), fl(qC[c])) for c in Tc], key=lambda x: -x[0])
    out = dict(kind='lifted', identity_class_map=identity_map, label=('identity-control diagnostic (binary identity class map)' if identity_map else 'lifted coarse proposal'), coarse_cards=list(Cz.ccards), n_coarse_states=len(cstates), n_target_classes=len(Tc), K=K, n_fine_states=len(states),
               Z=str(Z), Z_U=str(Z_U), log2_ZU_over_Z=lg(ZU_over_Z), log2_B_over_ZU=lg(B_over_ZU), log2_K_hi=lg(K_hi), log2_K_lo=lg(K_lo), K_inflation=S.rows.K.inflation(), log2_kappa_exact_oracle=lg(kappa_exact), log2_C_over_Z=lg(C_over_Z), decomposition_check_log2=lg(decomposition), numerical_cap_inflation_log2=lg(numerical_inflation), B_cap_violations=B_viol,
               R_star=fl(Rstar), M2=fl(M2), log2_R_star=lg(Rstar), log2_M2=lg(M2), C_tight_over_Z=fl(Ctight / Zint), log2_C_tight_over_Z=lg(Ctight / Zint), cap_ratio_impl_over_tight=fl(C_int / Ctight) if Ctight > 0 else None, max_X_analyzed=fl(Xmax), ordering_ok=bool(1 <= M2 <= Rstar <= C_over_Z + F(1, 10 ** 12)), support_failure=support_fail, omitted_target_mass_fraction=fl(omitted / Z),
               M2_lift_check=fl(M2_lift), M2_coarse=fl(M2_coarse), M2_min_fixed_r=fl(M2_min), M2_min_fixed_r_lower=fl(M2_min_lo), M2_at_attaining_law=fl(M2_at_qm2), R_star_min_fixed_r=fl(Rstar_min), R_star_at_attaining_law=fl(Rstar_at_qr), log2_M2_min_fixed_r=lg(M2_min), log2_R_star_min_fixed_r=lg(Rstar_min),
               exact_upper_law=dict(R_star=fl(RU), M2=fl(M2U), log2_R_star=lg(RU), log2_M2=lg(M2U), log2_C_over_Z=lg(CU / Z)), H_c_mass_table=hc_mass[:64], H_c_table_columns=['p_C', 'H_c', 'p_C^2 H_c / q_C', 'q_C'], V_j=[float(x) for x in Vj], var_p_g_j=[float(x) for x in varp], second_moment_precision='double (relative error <= 2 n_states u); exact: Z, Z_U, T_c, H_c, t_c, q, R*, M2, C_tight, limits', constant_responses=[int(j) for j in range(K) if varp[j] < 1e-300], mu_j=[float(x) for x in mu], queries=[list(q) for q in S.queries],
               eps_num=S.eps_num, alpha=S.alpha, logU_capf=S.logU_capf, E_U=S.mbp.E_U, E_tot=S.E_tot, mb_splits=S.mbp.splits, mb_cap=S.cap_used, kappa_compact=S.rows.K.record())
    tables = dict(classes=classes, qC=qC, C_int=C_int, Ctight=Ctight, Zint=Zint, K=K, Wl=Wl, states=states, mu=mu)
    return out, tables


# ---------------------------------------------------------------- paired reference replays (treatments A-D on identical draws)
def replay_original(S, tables, enum, seeds, ndraws, deadline):
    K = tables['K']; sq = S.sq; sep = tables['sep']; pos = tables['pos']; cards = tables['cards']; sstates = tables['sstates']; idx_of = {s: i for i, s in enumerate(sstates)}
    logW = np.array([lg(w) for w in tables['Wint']])
    G = tables['G']; mu_true = np.asarray(tables['mu']); caps = dict(current=lg(tables['C_int']), tight=lg(tables['Ctight']) + 2 ** -40)
    strides = {}; m = 1
    for v in reversed(sep): strides[v] = m; m *= cards[v]
    def state_index(Sb):
        idx = np.zeros(Sb.shape[0], dtype=np.int64)
        for v in sep: idx += Sb[:, pos[v]] * strides[v]
        return idx
    order_map = np.full(m, -1, dtype=np.int64)
    for i, s in enumerate(sstates): order_map[sum(s[k] * strides[v] for k, v in enumerate(sep))] = i
    return run_replay(S.mbp, S.pos, S.batch_used, K, S.eps_num, S.alpha, caps, logW, None, G, mu_true, lambda Sb: order_map[state_index(Sb)], seeds, ndraws, deadline, direct_stream=S)


def replay_lifted(S, tables, enum, seeds, ndraws, deadline):
    K = tables['K']; n = S.n_par; classes = tables['classes']; cstates = sorted(tables['qC']); cidx = {c: i for i, c in enumerate(cstates)}; states = tables['states']; Wl = tables['Wl']
    logW = np.array([lg(F(S.scale_F) * w / S.M_par.scalar) if w > 0 else -np.inf for w in Wl]); logqC = np.array([lg(tables['qC'][c]) if tables['qC'][c] > 0 else -np.inf for c in cstates])
    Zarr = np.array(states, dtype=np.int64); G = np.zeros((len(states), K)); mu_true = np.asarray(tables['mu'])
    for j, (v, a) in enumerate(S.queries): G[:, j] = (Zarr[:, v] == a).astype(float)
    caps = dict(current=lg(tables['C_int']), tight=lg(tables['Ctight']) + 2 ** -40); R = S.rows
    strides_c = {}; m = 1
    for v in reversed(range(n)): strides_c[v] = m; m *= Cz_ccard(S, v)
    strides_f = {}; mf = 1
    for v in reversed(range(n)): strides_f[v] = mf; mf *= S.M_par.cards[v]
    fine_map = np.full(mf, -1, dtype=np.int64)
    for i, z in enumerate(states): fine_map[sum(z[v] * strides_f[v] for v in range(n))] = i
    def draw_fine(Sb, rng):
        B = Sb.shape[0]; z = np.zeros((B, n), dtype=np.int64); logr = np.zeros(B)
        for v in range(n):
            u = rng.integers(0, LD.Q, size=B, dtype=np.int64); cv = Sb[:, v]
            for c in np.unique(cv):
                rows = np.nonzero(cv == c)[0]; cum = np.asarray(R.cum[(v, int(c))], dtype=np.int64); k = np.searchsorted(cum, u[rows], side='right'); mem = np.asarray(R.members[v][int(c)], dtype=np.int64); cnt = np.asarray(R.counts[(v, int(c))], dtype=np.int64)
                z[rows, v] = mem[k]; logr[rows] += np.log2(cnt[k].astype(float)) - LD.Q_BITS
        fi = np.zeros(B, dtype=np.int64)
        for v in range(n): fi += z[:, v] * strides_f[v]
        return fine_map[fi], logr
    return run_replay(S.mbp, S.pos, S.batch_used, K, S.eps_num, S.alpha, caps, logW, None, G, mu_true, None, seeds, ndraws, deadline, direct_stream=S, lifted=(draw_fine, logqC, cidx, strides_c, n))


def Cz_ccard(S, v): return S.Cz.ccards[v]


def run_replay(mbp, pos, batch, K, eps_num, alpha, caps, logW, logq_tab, G, mu_true, idx_fn, seeds, ndraws, deadline, direct_stream=None, lifted=None):
    """identical draws (seeded rng) feed four Certificates: A (current cap, eps_num), B (tight cap, eps_num), C (current cap, 0), D (tight cap, 0); weights and responses from the oracle tables in log arithmetic"""
    treatments = dict(A=('current', eps_num), B=('tight', eps_num), C=('current', 0.0), D=('tight', 0.0)); res = dict(seeds={}, treatments={k: dict(cap=v[0], eps_num=v[1]) for k, v in treatments.items()}, draws=ndraws, checkpoints=CHECKPOINTS, batch=batch)
    for seed in seeds:
        if tnow() >= deadline: res['seeds'][str(seed)] = dict(censored='deadline before seed'); continue
        rng = np.random.default_rng(np.random.SeedSequence([seed, 7919])); certs = {k: IG.Certificate(K, alpha, v[1], float(EPS), 'targeted') for k, v in treatments.items()}
        draws = 0; logsum = {k: -np.inf for k in treatments}; logsum2 = {k: -np.inf for k in treatments}; logmax = {k: -np.inf for k in treatments}; zero = 0; chk = {k: [] for k in treatments}; ckpt_i = 0; t0 = tnow(); censored = None
        while draws < ndraws:
            if tnow() >= deadline: censored = 'deadline at %d draws' % draws; break
            Sb, logq_s, zero_row = mbp.sample_batch(rng, batch, pos)
            if lifted is None: idx = idx_fn(Sb); lw = logW[idx]; lq = logq_s; g = G[idx]
            else:
                draw_fine, logqC, cidx, strides_c, n = lifted; fi, logr = draw_fine(Sb, rng); lw = logW[fi]; lq = logq_s + logr; g = G[fi]
            dead = zero_row | ~np.isfinite(lw) | ((fi < 0) if lifted is not None else (idx < 0))
            for k, (capname, e) in treatments.items():
                logX = np.where(dead, -np.inf, lw - lq - caps[capname]); X = np.where(dead, 0.0, np.exp2(np.minimum(logX, 0.0)))
                assert np.all(logX[~dead] <= 1e-9), 'oracle weight exceeds the %s cap: max log2 X %r' % (capname, float(logX[~dead].max()))
                certs[k].update_batch(X, g); fin = logX[~dead]
                if fin.size: 
                    m_ = max(logmax[k], float(fin.max())); logsum[k] = np.logaddexp2(logsum[k], float(np.logaddexp2.reduce(fin))); logsum2[k] = np.logaddexp2(logsum2[k], float(np.logaddexp2.reduce(2 * fin))); logmax[k] = m_
            zero += int(dead.sum()); draws += Sb.shape[0]
            while ckpt_i < len(CHECKPOINTS) and draws >= CHECKPOINTS[ckpt_i]:
                for k in treatments:
                    lo, hi = certs[k].sets(); width = hi - lo; finite = np.isfinite(width); rad = np.where(finite, width / 2, 0.5); err = np.where(finite, np.maximum(np.abs(lo - mu_true), np.abs(hi - mu_true)), 1.0); covered = int((rad <= float(EPS)).sum()); contain = int(((lo <= mu_true + 1e-15) & (hi >= mu_true - 1e-15) | ~finite).sum())
                    ess = float(np.exp2(2 * logsum[k] - logsum2[k])) if np.isfinite(logsum2[k]) else 0.0; share = float(np.exp2(logmax[k] - logsum[k])) if np.isfinite(logsum[k]) else None
                    chk[k].append(dict(draws=draws, worst_radius=float(rad.max()), median_radius=float(np.median(rad)), p90_radius=float(np.percentile(rad, 90)), covered=covered, K=K, contains_truth=contain, empty_sets=int((~finite).sum()), max_abs_err=float(err.max()), mean_log2_X=(float(logsum[k] - math.log2(draws)) if np.isfinite(logsum[k]) else None), ESS_stable=ess, largest_share=share, zero_fraction=zero / draws, t_s=round(tnow() - t0, 3)))
                ckpt_i += 1
        res['seeds'][str(seed)] = dict(draws=draws, censored=censored, checkpoints={k: chk[k] for k in treatments}, invariance_check=dict(ESS_A_vs_B=(chk['A'][-1]['ESS_stable'], chk['B'][-1]['ESS_stable']) if chk['A'] and chk['B'] else None, share_A_vs_B=(chk['A'][-1]['largest_share'], chk['B'][-1]['largest_share']) if chk['A'] and chk['B'] else None))
    # direct production-stream trace alongside (seed 1, same number of batches as the shortest completed replay)
    if direct_stream is not None and tnow() < deadline:
        S = direct_stream; nb = min(32, ndraws // max(1, S.batch_used)); t0 = tnow()
        for _ in range(nb):
            if tnow() >= deadline or S.stage != 'READY': break
            S.batch(deadline)
        S.check(); d = S.diagnostics(); res['direct_stream_trace'] = dict(draws=S.draws, X_mean=d.get('X_mean'), log2_X_mean=(math.log2(d['X_mean']) if d.get('X_mean') else None), zero_weight_fraction=d.get('zero_weight_fraction'), max_log2_X_observed=d.get('max_log2_X_observed'), published=len(S.pub), valid_endpoints=len(S.endpoints), max_remaining_width=S.max_unresolved_width(), stage=S.stage, closed=S.closed_reason, seconds=round(tnow() - t0, 3), note='the production stream on the SAME model with its float tables (seed = the stream seed); the reference replay uses the exact oracle tables')
    return res


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('model'); ap.add_argument('out'); ap.add_argument('--cap-s', type=float, default=100.0); ap.add_argument('--replay-draws', type=int, default=1 << 18); ap.add_argument('--seeds', default='1,2,3'); ap.add_argument('--no-replay', action='store_true'); ap.add_argument('--laws', default='original,lifted'); a = ap.parse_args()
    t_start = tnow(); deadline = t_start + a.cap_s; model, binding = CORE.read_uai(a.model); out = dict(model=os.path.abspath(a.model), binding=binding, profile=PROFILE, cap_s=a.cap_s, utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), phases={}, censored=[])
    clk = CE.Clock(deadline, {}); B = CE.Budget(CE.CONSTRUCTOR_BYTES); M = CE.canonicalize(model, clk, B); n_states = math.prod(M.cards); out['canonical'] = dict(variables=len(M.cards), cards=list(M.cards), fine_states=n_states, scalar=str(M.scalar), factors=len(M.factors))
    assert n_states <= 1 << 16, 'oracle panel models must have <= 2^16 fine states'
    try:
        t0 = tnow(); enum = enumerate_original(M, deadline); out['phases']['enumeration'] = tnow() - t0; out['original'] = dict(Z=str(enum['Z']), log2_Z=lg(enum['Z']), K=len(enum['mu']), marginals=[[int(v), a, str(mu)] for (v, a), mu in sorted(enum['mu'].items())])
        st = PA.RequestState(model, binding, EPS, DELTA); PA.structural_routes(st, deadline, flags=dict(evidence_expansion=False, layered_contraction=False, ancestral_response=False, support_closure=True))
        laws = a.laws.split(',')
        if 'original' in laws:
            t0 = tnow(); S1, r1 = original_stream(st, 1, deadline); out['phases']['original_stream_prepare'] = tnow() - t0
            if r1 == 'READY':
                t0 = tnow(); q1, tab1 = original_quantities(S1, enum, M, deadline); out['phases']['original_quantities'] = tnow() - t0; out['original_stream'] = q1
                if not a.no_replay: t0 = tnow(); out['original_replay'] = replay_original(S1, tab1, enum, [int(x) for x in a.seeds.split(',')], a.replay_draws, deadline); out['phases']['original_replay'] = tnow() - t0
            else: out['original_stream'] = dict(stage=S1.stage, closed=S1.closed_reason, terminal=S1.mech.get('terminal'), note='the stream did not reach READY under the diagnostic profile (recorded branch)')
        if 'lifted' in laws:
            t0 = tnow(); S2, r2, classes, Cz = lifted_stream(M, 1, deadline, B); out['phases']['lifted_stream_prepare'] = tnow() - t0
            if S2 is not None and r2 == 'READY':
                t0 = tnow(); q2, tab2 = lifted_quantities(S2, classes, Cz, enum, M, deadline); out['phases']['lifted_quantities'] = tnow() - t0; out['lifted_stream'] = q2
                if not a.no_replay: t0 = tnow(); out['lifted_replay'] = replay_lifted(S2, tab2, enum, [int(x) for x in a.seeds.split(',')], a.replay_draws, deadline); out['phases']['lifted_replay'] = tnow() - t0
            else: out['lifted_stream'] = dict(stage=(S2.stage if S2 else None), closed=(S2.closed_reason if S2 else r2), note='the lifted stream did not reach READY (recorded construction branch)')
    except Deadline as e: out['censored'].append(str(e))
    out['wall_s'] = tnow() - t_start; json.dump(out, open(a.out, 'w'), indent=1, default=str)
    print(json.dumps(dict(model=os.path.basename(a.model), wall=round(out['wall_s'], 2), censored=out['censored'], orig=(out.get('original_stream') or {}).get('log2_C_over_Z'), orig_tight=(out.get('original_stream') or {}).get('log2_C_tight_over_Z'), orig_M2=(out.get('original_stream') or {}).get('log2_M2'), lift=(out.get('lifted_stream') or {}).get('log2_C_over_Z'), lift_M2=(out.get('lifted_stream') or {}).get('log2_M2'), lift_M2min=(out.get('lifted_stream') or {}).get('log2_M2_min_fixed_r'), lift_Rmin=(out.get('lifted_stream') or {}).get('log2_R_star_min_fixed_r'), identity=(out.get('lifted_stream') or {}).get('identity_class_map')), default=str))


if __name__ == '__main__': main()
