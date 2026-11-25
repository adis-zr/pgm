"""DGP3 oracle harness (PROTOCOL.md section 5): for one <= 2^16-state model, (1) exact enumeration (dgp2_oracle); (2) the ORIGINAL stream under the frozen forced-PAC profile with its quantities and the PAIRED ARITHMETIC
DIAGNOSTIC (same production draws: exact W_int, exact analyzed q and exact responses evaluated on each drawn assignment vs the implemented float log2 X); (3) the LIFTED stream at envelope levels G1 / G2 / G3 under
the frozen forced profile (and, as a labelled secondary diagnostic, under the production mini-bucket cap 2^24, where the coarse law is the exact-upper law of the grouped model): Z_U^G / Z, B / Z_U, C / Z in W_int
units, C_tight / Z, M2, R*, the fixed-r limits (unchanged across G), the envelope validity by enumeration and the dominance U_g <= prod U_f; (4) the cap-optimal and M2-optimal coarse laws' replays (the DGP2 review's
counterfactual, retained) and the realized G1 / G2 laws' replays A (current cap) / B (tight cap), 2^18 draws x seeds 1-3; (5) the BLOCK-DECODER oracle: variables paired by the frozen rule (consecutive pairs of the
variable order), r_B(z_B | c_B) = the normalized exact restriction of the intra-block factors x unaries within the block's coarse cell (checked by enumeration), its fixed-r limits M2_min^(r_B), R*_min^(r_B), and the
cap-optimal replay. ORACLE ONLY. usage: dgp3_oracle.py MODEL.uai OUT.json [--cap-s 100] [--replay-draws 262144] [--seeds 1,2,3]"""
import sys, os, json, time, math, argparse, itertools
from fractions import Fraction as F
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), 'cex', 'newarm')); sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), 'cex', 'blockres'))
import coarse_envelope as CE, pac_actions as PA, lifted_decoder as LD, grouped_envelope as GE, integrated as IG, core as CORE, dgp2_oracle as O2
from dgp2_oracle import EPS, DELTA, PROFILE, CHECKPOINTS, fl, lg, Deadline, sqrt_up, sqrt_dn, tnow
PROD_PROFILE = dict(PROFILE, mb_cap=1 << 24)                                                    # labelled secondary diagnostic: production mini-bucket cap (the coarse law becomes the exact-upper law on these tiny models)
LEVELS = ('G1', 'G2', 'G3')


def envelope_check(M, classes, Cz, enum, ufn, deadline):
    """oracle: lemma G validity by enumeration, W(z) <= G_U(c(z)) d(z) on EVERY fine state (W from the enumeration, G_U cached per coarse state, d from the decoder tables); polled every 4,096 states;
    returns dict(valid, zero_weight_states, max_W_over_envelope)"""
    n = len(M.cards); GU = {}; worst = F(0); zero = 0
    for i, (z, w) in enumerate(zip(enum['states'], enum['W'])):
        if (i & 4095) == 4095 and tnow() >= deadline: raise Deadline('envelope check')
        c = tuple(classes[v][z[v]] for v in range(n))
        if c not in GU: GU[c] = ufn(c)
        d = F(1)
        for v in range(n): d *= Cz.d[v][z[v]]
        G = GU[c] * d
        if w > G: raise CE.Defect('upper envelope violated at %s: W %s > G_U d %s' % (z, w, G))
        if w == 0: zero += 1
        elif G > 0 and w / G > worst: worst = w / G
    return dict(valid=True, zero_weight_states=zero, max_W_over_envelope=lg(worst) if worst > 0 else None, coarse_states_checked=len(GU))


def complete_record(d):
    """a recorded phase is reusable only when nothing inside it is censored (no nested dict carries a truthy 'censored')"""
    if isinstance(d, dict):
        if d.get('censored'): return False
        return all(complete_record(v) for v in d.values())
    if isinstance(d, list): return all(complete_record(v) for v in d)
    return True


def paired_arithmetic(S, enum, M, n_batches, deadline):
    """DGP2 review RF4: on the ORIGINAL stream's own production draws, compare the implemented float log2 X with the exact analyzed log2 X computed independently on the SAME assignments (exact W_int from the live block
    tables, exact q from the sampler's exact replay logq_given, exact cap); returns max / p99 / mean of |delta log2 X| and the consumed rho_X bound"""
    cards = S.cards; sep = list(S.S); pos = S.pos; flat = [np.asarray(b.arr, dtype=object).reshape(-1).tolist() for b in S.live_blocks]; scopes = [b.scope for b in S.live_blocks]
    C_int = F(2) ** int(math.floor(S.logU_capf)) * F(2.0 ** (S.logU_capf - math.floor(S.logU_capf))) * F(2) ** S.mbp.E_U; devs = []; n = 0
    for _ in range(n_batches):
        if tnow() >= deadline: raise Deadline('paired arithmetic')
        Sb, logq_s, zero_row = S.mbp.sample_batch(S.rng, S.batch_used, pos); B = Sb.shape[0]; logz = np.zeros(B)
        for i in range(len(S.blocks)): logz += S.bLM[i][S._flat_index(Sb, i)]
        zero = ~np.isfinite(logz) | zero_row; logX_impl = (logz - logq_s - S.logU_capf) + float(S.E_tot)
        lq, q_an = S.mbp.logq_given(Sb, pos)
        for k in range(B):
            if zero[k] or q_an[k] == 0: continue
            w = 1
            for fb, sc in zip(flat, scopes):
                idx = 0
                for x in sc: idx = idx * cards[x] + int(Sb[k, pos[x]])
                w *= int(fb[idx])
            X_an = F(w) / (C_int * q_an[k]); devs.append(abs(float(logX_impl[k]) - lg(X_an))); n += 1
    d = np.array(devs); rho_X = S.mech.get('rho_X')
    return dict(draws=n, max_abs_log2_dev=float(d.max()) if d.size else None, p99_abs_log2_dev=float(np.percentile(d, 99)) if d.size else None, mean_abs_log2_dev=float(d.mean()) if d.size else None, consumed_rho_X=rho_X, bound_log2_from_rho_X=(math.log2(1 + rho_X) if rho_X else None), within_bound=bool(d.size and d.max() <= math.log2(1 + 2 * rho_X) + 1e-12) if rho_X else None, note='same production assignments; exact W_int (integer block products), exact analyzed q (logq_given), exact cap; the implemented value uses the float block log tables')


def block_decoder(M, classes, Cz, enum, deadline):
    """the competing hypothesis: blocks of two variables (consecutive in the canonical order; a trailing singleton stays alone); within a block, r_B(z_B | c_B) ∝ prod_{v in B} u_v(z_v) prod_{f inside B} h_f(z_B) on the
    block's coarse cell (exact, gauge-residual tables as the product decoder uses), normalized per (block, cell); r_B(z | c) = prod_B r_B(z_B | c_B). Fixed-r limits with this r_B (lemma R applies verbatim with r_B
    in place of r). Returns the quantities, the per-fine-state r_B (for the replay), t_c^B and T_c. Polled every 4,096 states."""
    n = len(M.cards); blocks = [tuple(range(i, min(i + 2, n))) for i in range(0, n, 2)]; scopes = [tuple(sc) for sc, _ in M.factors]
    inside = {b: [fi for fi, sc in enumerate(scopes) if set(sc) <= set(b)] for b in blocks}
    # per-block tables over the block's FINE assignments (<= card^2 entries): m_B(z_B) and the (block, cell) normalizers
    mtab = {}; tot = {}
    for b in blocks:
        for zb in itertools.product(*[range(M.cards[v]) for v in b]):
            m = F(1)
            for k, v in enumerate(b): m *= Cz.u[v][zb[k]]
            for fi in inside[b]:
                sc = scopes[fi]; vals = M.factors[fi][1]; fst = CE.strides([M.cards[v] for v in sc]); e = vals[sum(fst[ax] * zb[b.index(v)] for ax, v in enumerate(sc))]
                for ax, v in enumerate(sc): e = e / Cz.scales[(fi, ax)][zb[b.index(v)]]
                m *= e
            cb = tuple(classes[v][zb[k]] for k, v in enumerate(b)); mtab[(b, zb)] = m; tot[(b, cb)] = tot.get((b, cb), F(0)) + m
        if tnow() >= deadline: raise Deadline('block decoder tables')
    states = enum['states']; W = enum['W']; Z = enum['Z']; cmap = [tuple(classes[v][z[v]] for v in range(n)) for z in states]; rB = []
    for i, (z, c) in enumerate(zip(states, cmap)):
        if (i & 4095) == 4095 and tnow() >= deadline: raise Deadline('block decoder r_B')
        r = F(1)
        for b in blocks:
            zb = tuple(z[v] for v in b); cb = tuple(c[v] for v in b); t = tot[(b, cb)]; r *= (mtab[(b, zb)] / t) if t > 0 else F(0)
        rB.append(r)
    Tc = {}; Hc = {}; tc = {}; norm = {}
    for i, (z, w, c, r) in enumerate(zip(states, W, cmap, rB)):
        if (i & 4095) == 4095 and tnow() >= deadline: raise Deadline('block decoder moments')
        Tc[c] = Tc.get(c, F(0)) + w; norm[c] = norm.get(c, F(0)) + r
        if w > 0 and r == 0: raise CE.Defect('block decoder: zero r_B on a positive-weight state')
    bad_norm = [c for c, s_ in norm.items() if abs(s_ - 1) > F(1, 10 ** 20)]
    for i, (z, w, c, r) in enumerate(zip(states, W, cmap, rB)):
        if (i & 4095) == 4095 and tnow() >= deadline: raise Deadline('block decoder limits')
        if Tc[c] > 0 and r > 0 and w > 0: p = w / Tc[c]; Hc[c] = Hc.get(c, F(0)) + p * p / r; tc[c] = max(tc.get(c, F(0)), w / r)
    pC = {c: Tc[c] / Z for c in Tc}; M2_min = sum(pC[c] * sqrt_up(Hc[c]) for c in Hc) ** 2; R_min = sum(tc.values()) / Z
    return dict(blocks=[list(b) for b in blocks], factors_inside_blocks=sum(len(v) for v in inside.values()), n_factors=len(scopes), normalization_violations=len(bad_norm), log2_M2_min_fixed_rB=lg(M2_min), log2_R_star_min_fixed_rB=lg(R_min), M2_min_fixed_rB=fl(M2_min), R_star_min_fixed_rB=fl(R_min), pairing_rule='consecutive variables of the canonical order'), rB, tc, Tc


def replay_fine_law(states, W, Z, G, mu, qlog, log2_Rstar, K, alpha, eps_num, seeds, ndraws, deadline, label):
    """oracle replay of ONE fine-state law given as log2 q per fine state with its TIGHT cap R* (outward 2^-40): X = (W / Z) / (q R*); inverse-CDF draws (one law, one cap; different laws do not share draws);
    the accepted Certificate at risk alpha per coordinate and the lifted stream's numerical allowance; checkpoints as dgp2_oracle.CHECKPOINTS"""
    logW_norm = np.array([lg(w / Z) if w > 0 else -np.inf for w in W]); fin = np.isfinite(qlog); q = np.where(fin, np.exp2(qlog - qlog[fin].max()), 0.0); q = q / q.sum(); cdf = np.cumsum(q); cdf[-1] = 1.0
    logX = np.where(q > 0, logW_norm - np.log2(np.where(q > 0, q, 1.0)) - (log2_Rstar + 2.0 ** -40), -np.inf); assert np.all(logX[np.isfinite(logX)] <= 1e-9), 'oracle weight exceeds the tight cap'; X = np.where(np.isfinite(logX), np.exp2(np.minimum(logX, 0.0)), 0.0); rep = dict(label=label, draws=ndraws, log2_cap=log2_Rstar, seeds={})
    for seed in seeds:
        if tnow() >= deadline: rep['seeds'][str(seed)] = dict(censored='deadline'); continue
        rng = np.random.default_rng(np.random.SeedSequence([seed, 31337])); cert = IG.Certificate(K, alpha, eps_num, float(EPS), 'targeted'); draws = 0; chk = []
        while draws < ndraws:
            ix = np.minimum(np.searchsorted(cdf, rng.random(1024), side='right'), len(cdf) - 1); cert.update_batch(X[ix], G[ix]); draws += 1024
            if draws in CHECKPOINTS: lo, hi = cert.sets(); width = hi - lo; fn = np.isfinite(width); rad = np.where(fn, width / 2, 0.5); chk.append(dict(draws=draws, worst_radius=float(rad.max()), median_radius=float(np.median(rad)), p90_radius=float(np.percentile(rad, 90)), covered=int((rad <= float(EPS)).sum()), K=K, contains_truth=int((((lo <= mu + 1e-15) & (hi >= mu - 1e-15)) | ~fn).sum())))
        rep['seeds'][str(seed)] = dict(checkpoints=chk)
    return rep


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('model'); ap.add_argument('out'); ap.add_argument('--cap-s', type=float, default=100.0); ap.add_argument('--replay-draws', type=int, default=1 << 18); ap.add_argument('--seeds', default='1,2,3'); ap.add_argument('--arith-batches', type=int, default=4); ap.add_argument('--continue', dest='cont', action='store_true', help='reuse every completed phase recorded in OUT.json (streams rebuilt deterministically); only the missing phases run'); a = ap.parse_args()
    t_start = tnow(); deadline = t_start + a.cap_s; seeds = [int(x) for x in a.seeds.split(',')]; model, binding = CORE.read_uai(a.model); prev = json.load(open(a.out)) if (a.cont and os.path.exists(a.out)) else {}
    out = dict(model=os.path.abspath(a.model), binding=binding, profile=PROFILE, production_cap_profile=PROD_PROFILE, cap_s=a.cap_s, utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), phases=dict(prev.get('phases') or {}), censored=[], continued_from=(dict(utc=prev.get('utc'), wall_s=prev.get('wall_s'), censored=prev.get('censored')) if prev else None))
    def have(*keys):
        d = prev
        for k in keys:
            if not isinstance(d, dict) or k not in d: return None
            d = d[k]
        return d if (isinstance(d, dict) and complete_record(d)) else None
    clk = CE.Clock(deadline, {}); B = CE.Budget(CE.CONSTRUCTOR_BYTES); M = CE.canonicalize(model, clk, B); n = len(M.cards); assert math.prod(M.cards) <= 1 << 16
    try:
        t0 = tnow(); enum = O2.enumerate_original(M, deadline); out['phases']['enumeration'] = tnow() - t0; Z = enum['Z']; out['original'] = dict(Z=str(Z), log2_Z=lg(Z), K=len(enum['mu']))
        st = PA.RequestState(model, binding, EPS, DELTA); PA.structural_routes(st, deadline, flags=dict(evidence_expansion=False, layered_contraction=False, ancestral_response=False, support_closure=True))
        t0 = tnow(); S1, r1 = O2.original_stream(st, 1, deadline); out['phases']['original_prepare'] = tnow() - t0
        if r1 == 'READY':
            if have('original_stream') and have('original_replay') and have('paired_arithmetic'): out['original_stream'] = prev['original_stream']; out['paired_arithmetic'] = prev['paired_arithmetic']; out['original_replay'] = prev['original_replay']; out.setdefault('reused', []).append('original')
            else:
                t0 = tnow(); q1, tab1 = O2.original_quantities(S1, enum, M, deadline); out['original_stream'] = q1; out['phases']['original_quantities'] = tnow() - t0
                t0 = tnow(); out['paired_arithmetic'] = paired_arithmetic(S1, enum, M, a.arith_batches, deadline); out['phases']['paired_arithmetic'] = tnow() - t0
                t0 = tnow(); out['original_replay'] = O2.replay_original(S1, tab1, enum, seeds, a.replay_draws, deadline); out['phases']['original_replay'] = tnow() - t0
        else: out['original_stream'] = dict(stage=S1.stage, closed=S1.closed_reason, terminal=S1.mech.get('terminal'), note='did not reach READY under the diagnostic profile (recorded branch)')
        prof, why = CE.slice_profiles(M, clk, B)
        if prof is None: out['lifted'] = dict(note='proposer unavailable: ' + str(why)); raise Deadline('no lifted stage') if False else None
        else:
            classes = [CE.canonical_classes(CE.farthest_split(prof[v], list(range(M.cards[v])), clk), M.cards[v]) for v in range(n)]; Cz = CE.check_candidate(M, classes, CE.unit_scales(M), clk, B, ratio_product='compact'); identity = all(len(set(cl)) == len(cl) for cl in classes)
            out['lifted'] = dict(identity_class_map=identity, coarse_cards=list(Cz.ccards), levels={}, levels_production_cap={})
            states = enum['states']; W = enum['W']; cmap = [tuple(classes[v][z[v]] for v in range(n)) for z in states]; Zarr = np.array(states, dtype=np.int64); K = sum(M.cards); G = np.zeros((len(states), K)); j = 0; queries = []
            for v in range(n):
                for a_ in range(M.cards[v]): G[:, j] = (Zarr[:, v] == a_).astype(float); queries.append((v, a_)); j += 1
            E = max(1, max(w.numerator.bit_length() - w.denominator.bit_length() for w in W if w > 0)) - 60; pf = np.array([float(w / F(2) ** E) if w > 0 else 0.0 for w in W]); pf = pf / pf.sum(); mu = (pf[:, None] * G).sum(axis=0)
            Sref = None
            small = len(states) <= (1 << 14); out['lifted']['production_cap_secondary'] = ('computed (model <= 2^14 states)' if small else 'skipped on this model (> 2^14 fine states; labelled secondary diagnostic, PROTOCOL section 4 oracle cap)')
            cache = {}; Sref = None; tabref = None
            def level(prof_name, profile, slot, lv, replay):
                nonlocal Sref, tabref
                if have('lifted', slot, lv) and (not replay or 'replay' in prev['lifted'][slot][lv]):
                    out['lifted'][slot][lv] = prev['lifted'][slot][lv]; out.setdefault('reused', []).append('%s:%s' % (slot, lv))
                    if prof_name == 'forced' and lv == 'G1' and Sref is None: S = PA.LiftedStream(2, M, M, [], classes, Cz, 1, EPS, DELTA / 4, dict(profile, budget_obj=B), envelope=lv); assert S.prepare(deadline) == 'READY'; Sref = S
                    return
                if tnow() >= deadline: raise Deadline('lifted %s %s' % (prof_name, lv))
                t0 = tnow(); S = PA.LiftedStream(2, M, M, [], classes, Cz, 1, EPS, DELTA / 4, dict(profile, budget_obj=B), envelope=lv); r = S.prepare(deadline); prep = tnow() - t0
                if r != 'READY': out['lifted'][slot][lv] = dict(stage=S.stage, closed=S.closed_reason, prep_s=prep); return
                q2, tab2 = O2.lifted_quantities(S, classes, Cz, enum, M, deadline, cache=cache); ufn = S.upper_weight_fn(); chk = envelope_check(M, classes, Cz, enum, ufn, deadline); dom = GE.check_dominance(M, Cz, S.grouped['tables'], S.grouped['groups']) if S.grouped else True
                row = dict(prep_s=prep, grouped=S.mech.get('grouped_envelope'), envelope_valid=chk['valid'], envelope_max_log2_W_over_GUd=chk['max_W_over_envelope'], dominance=dom, zero_weight_states=chk['zero_weight_states'], **{k: q2[k] for k in ('log2_ZU_over_Z', 'log2_B_over_ZU', 'log2_K_hi', 'log2_C_over_Z', 'log2_C_tight_over_Z', 'cap_ratio_impl_over_tight', 'log2_M2', 'log2_R_star', 'max_X_analyzed', 'ordering_ok', 'support_failure', 'B_cap_violations', 'numerical_cap_inflation_log2', 'M2_coarse', 'log2_M2_min_fixed_r', 'log2_R_star_min_fixed_r', 'exact_upper_law', 'eps_num', 'mb_splits', 'mb_cap', 'H_c_mass_table')}, cap_units=S.mech.get('cap_units'), V_j_max=float(max(q2['V_j'])), V_j_median=float(np.median(q2['V_j'])))
                out['lifted'][slot][lv] = row                                                                   # recorded BEFORE the replay (a censored replay keeps the quantities)
                if prof_name == 'forced' and lv == 'G1': Sref = S; tabref = tab2
                if replay: t0 = tnow(); row['replay'] = O2.replay_lifted(S, tab2, enum, seeds, a.replay_draws, deadline); row['replay_s'] = tnow() - t0
            level('forced', PROFILE, 'levels', 'G1', True); level('forced', PROFILE, 'levels', 'G2', True)
            # the review's counterfactual laws with the DGP2 decoder r (G1 rows): cap-optimal q_C ∝ t_c and M2-optimal q_C ∝ p_C sqrt(H_c); replays with their tight caps
            if have('lifted', 'counterfactual_laws_same_decoder'): out['lifted']['counterfactual_laws_same_decoder'] = prev['lifted']['counterfactual_laws_same_decoder']; out.setdefault('reused', []).append('counterfactual')
            elif Sref is not None and tnow() < deadline:
                if 'rvals' not in cache:
                    rprob = [[{a_: LD.r_prob(Sref.rows, v, c, a_) for a_ in Sref.rows.members[v][c]} for c in range(Cz.ccards[v])] for v in range(n)]; rvals = []; Tc = {}; Hc = {}; tc = {}
                    for i, (z, w, c) in enumerate(zip(states, W, cmap)):
                        if (i & 4095) == 4095 and tnow() >= deadline: raise Deadline('counterfactual r')
                        r_ = F(1)
                        for v in range(n): r_ *= rprob[v][c[v]][z[v]]
                        rvals.append(r_); Tc[c] = Tc.get(c, F(0)) + w
                    for z, w, c, r_ in zip(states, W, cmap, rvals):
                        if w > 0 and r_ > 0: p = w / Tc[c]; Hc[c] = Hc.get(c, F(0)) + p * p / r_; tc[c] = max(tc.get(c, F(0)), w / r_)
                    cache.update(rvals=rvals, Hc=Hc, tc=tc)
                rvals = cache['rvals']; Hc = cache['Hc']; tc = cache['tc']; Tc = {}
                for c, w in zip(cmap, W): Tc[c] = Tc.get(c, F(0)) + w
                pC = {c: Tc[c] / Z for c in Tc}; alpha = float(DELTA / 4) / K; eps_num = Sref.eps_num; laws = {}
                tsum = sum(tc.values()); wts = {c: pC[c] * sqrt_up(Hc[c]) for c in Hc}; wsum = sum(wts.values())                     # normalizers ONCE (the frozen version recomputed them inside the comprehension: quadratic in the class count, stalled on the 4,096-class identity maps; FREEZE_AMENDMENT_harness1)
                for name, qc in (('cap_optimal_same_decoder', {c: tc[c] / tsum for c in tc}), ('M2_optimal_same_decoder', {c: wts[c] / wsum for c in Hc})):
                    if tnow() >= deadline: raise Deadline('counterfactual ' + name)
                    qlog = np.array([lg(qc.get(c, F(0)) * r_) if (qc.get(c, F(0)) > 0 and r_ > 0) else -np.inf for c, r_ in zip(cmap, rvals)])
                    # R* and M2 of the law from the per-class quantities (exact; lemma R): R* = max_c t_c / (Z q_C(c)), M2 = sum_c p_C^2 H_c / q_C
                    Rstar = max(tc[c] / (Z * qc[c]) for c in tc if qc.get(c, F(0)) > 0); M2 = sum(pC[c] ** 2 * Hc[c] / qc[c] for c in Hc if qc.get(c, F(0)) > 0)
                    laws[name] = dict(log2_R_star=lg(Rstar), log2_M2=lg(M2), replay=replay_fine_law(states, W, Z, G, mu, qlog, lg(Rstar), K, alpha, eps_num, seeds, a.replay_draws, deadline, name))
                out['lifted']['counterfactual_laws_same_decoder'] = laws
            # block-decoder oracle (competing hypothesis)
            if have('block_decoder') and 'cap_optimal_law' in prev['block_decoder']: out['block_decoder'] = prev['block_decoder']; out.setdefault('reused', []).append('block_decoder')
            elif tnow() < deadline:
                t0 = tnow(); bd, rB, tcB, TcB = block_decoder(M, classes, Cz, enum, deadline); out['phases']['block_decoder'] = tnow() - t0; out['block_decoder'] = bd
                if tnow() < deadline and sum(tcB.values()) > 0:
                    tsumB = sum(tcB.values()); qcB = {c: tcB[c] / tsumB for c in tcB}; qlog = np.array([lg(qcB.get(c, F(0)) * r_) if (qcB.get(c, F(0)) > 0 and r_ > 0) else -np.inf for c, r_ in zip(cmap, rB)]); RstarB = max(tcB[c] / (Z * qcB[c]) for c in tcB if qcB[c] > 0)
                    eps_b = (out['lifted']['levels'].get('G1') or {}).get('eps_num') or 1e-11; bd['cap_optimal_law'] = dict(log2_R_star=lg(RstarB), replay=replay_fine_law(states, W, Z, G, mu, qlog, lg(RstarB), K, float(DELTA / 4) / K, eps_b, seeds, a.replay_draws, deadline, 'block_decoder_cap_optimal'))
            level('forced', PROFILE, 'levels', 'G3', False)
            if small:
                for lv in LEVELS: level('production_cap', PROD_PROFILE, 'levels_production_cap', lv, False)
    except Deadline as e: out['censored'].append(str(e))
    out['wall_s'] = tnow() - t_start; json.dump(out, open(a.out, 'w'), indent=1, default=str)
    lv = (out.get('lifted') or {}).get('levels') or {}; print(json.dumps(dict(model=os.path.basename(a.model), wall=round(out['wall_s'], 2), censored=out['censored'], orig_CZ=(out.get('original_stream') or {}).get('log2_C_over_Z'), arith_max=(out.get('paired_arithmetic') or {}).get('max_abs_log2_dev'), G=[(k, round(v.get('log2_ZU_over_Z', -1), 2), round(v.get('log2_C_over_Z', -1), 2), round(v.get('log2_C_tight_over_Z', -1), 2), round(v.get('log2_M2', -1), 2)) for k, v in lv.items()], blockdec=((out.get('block_decoder') or {}).get('log2_M2_min_fixed_rB'), (out.get('block_decoder') or {}).get('log2_R_star_min_fixed_rB'))), default=str))


if __name__ == '__main__': main()
