"""DGP4 oracle harness (PROTOCOL.md section 5; brief section 7): for one <= 2^16-state model -- (1) exact enumeration (dgp2_oracle); (2) the FAST classes and the ACTUAL dyadic decoder rows (frozen); the raw rational
reference t(c) = max_{x in c} W_0(x) / r(x | c), T = sum t, Z_0 = Z / scalar; (3) constructions under the SAME classes / gauge / decoder / coarse-sampler settings (requested coarse MB cap 2^24, the same memory ladder):
repaired G2 and RMAX at V in {64, 256, 1024, 4096} -- per construction: READY / refusal, the realized analyzed law q_C, its tight cap R*(q) = max_x (W_0 / Z_0) / (q_C r), the implemented certified B (W_0 units: C_int /
scale_F), sum U (RMAX: packed, and the compact pre-packing closure; G2: sum_c G_U(c) K_hi), the prefix-zero closure sum, retained compatibility (messages consumed by later eliminations), MAX splits, work cells, preparation
seconds, owned peak bytes, packing inflation, checker receipt; both decompositions log2(B / T) = log2(B / sum U) + log2(sum U / T) and log2(B / T) = log2((B / Z_0) / R*) + log2(R* / (T / Z_0)); sum p^2 / q (M2) and the
requested-response second moments V_j (G2 and RMAX V4096); (4) with --replay: the accepted certificate replayed for 2^18 draws x seeds 1-3 for the realized G2 and RMAX V4096 laws (implemented cap / tight cap on the SAME
draws: dgp2_oracle.replay_lifted treatments A / B) and the fixed-decoder ideal law q_C = t / T under its tight cap T / Z_0 and under the cap required by each arm's retained U (sum U / Z_0) -- labelled counterfactuals.
(5) harness amendment 3 (DGP4 review): counterfactual laws q_T = t / T (cap-optimal) and q_2 proportional to sqrt(A_c) (moment-optimal) replayed under their TIGHT caps and under the cap each retained envelope actually requires, B_U(q) = max_c U(c) / q(c) (checked at every coarse state); the frozen 'required_by_*_sumU' column is relabelled an oracle-only numerical-cap counterfactual; the checked cap / moment frontier of the retained RMAX envelope. --continue reuses every completed phase. ORACLE ONLY. usage: dgp4_oracle.py MODEL.uai OUT.json [--cap-s 100] [--replay] [--replay-draws 262144] [--seeds 1,2,3] [--continue]"""

# Source-checkout entry point; production imports never traverse research.
if __package__ in (None, ""):
    import sys as _research_sys
    from pathlib import Path as _ResearchPath
    _research_sys.path.insert(0, str(_ResearchPath(__file__).resolve().parents[3]))
from research.bootstrap import activate as _activate_research
_activate_research()
from research.paths import repo_root as _repo_root, runs_root as _runs_root, records_root as _records_root, source_path as _source_path
import sys, os, json, time, math, argparse, itertools
from fractions import Fraction as F
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
import pgm.algorithms.quotient.coarse_envelope as CE, pgm.algorithms.quotient.pac_actions as PA, pgm.algorithms.quotient.lifted_decoder as LD, pgm.algorithms.quotient.grouped_envelope as GE, pgm.algorithms.quotient.residual_max_envelope as RM, pgm.algorithms.block.integrated as IG, pgm.algorithms.structural.core as CORE, research.campaigns.hp.dgp2_oracle as O2, research.campaigns.hp.dgp3_oracle as O3
from research.campaigns.hp.dgp2_oracle import EPS, DELTA, CHECKPOINTS, fl, lg, Deadline, tnow
from pgm.algorithms.quotient.unified_pac_planner import PAC_OPTS
PROFILE = dict(PAC_OPTS, mb_cap=1 << 24)                                                        # the production coarse-sampler settings (requested MB cap 2^24; the same memory ladder) for BOTH constructions
WIDTHS = list(RM.ORACLE_WIDTHS)


def per_class_reference(enum, M, cmap, rvals, deadline):
    """ONE pass over the fine states: t(c) = max_{x in c} W_0 / r, H2(c) = sum_{x in c} (W_0 / Z_0)^2 / r, class mass; the per-construction law quantities then aggregate over classes (O(#classes)):
    R*(q) = max_c t(c) / (Z_0 q_C(c)),  M2 = sum_c H2(c) / q_C(c),  max_X = max_c t(c) / (B q_C(c)),  support failure = a class with t(c) > 0 and q_C(c) = 0"""
    Z0 = enum['Z'] / M.scalar; t = {}; H2 = {}; mass = {}
    for i, (z, w, c, r_) in enumerate(zip(enum['states'], enum['W'], cmap, rvals)):
        if (i & 4095) == 4095 and tnow() >= deadline: raise Deadline('per-class reference')
        if w == 0: continue
        w0 = w / M.scalar; val = w0 / r_
        if val > t.get(c, F(0)): t[c] = val
        p = w0 / Z0; H2[c] = H2.get(c, F(0)) + p * p / r_; mass[c] = mass.get(c, F(0)) + w0
    return t, H2, mass


def law_quantities(S, enum, M, t, H2, mass, deadline):
    """R*(q), M2 = sum p^2 / q, max analyzed X and the implemented B (W_0 units) of the stream's realized analyzed law, aggregated over classes (exact rationals)"""
    Z0 = enum['Z'] / M.scalar; cstates = list(itertools.product(*[range(k) for k in S.Cz.ccards])); Sb = np.array(cstates, dtype=np.int64); lq, q_C = S.mbp.logq_given(Sb, S.pos); qC = dict(zip(cstates, q_C))
    C_int = F(2) ** int(math.floor(S.logU_capf)) * F(2.0 ** (S.logU_capf - math.floor(S.logU_capf))) * F(2) ** S.mbp.E_U; B = C_int / F(S.scale_F); Rstar = F(0); M2 = F(0); Xmax = F(0); support_fail = 0; omitted = F(0)
    for c in t:
        q = qC.get(c, F(0))
        if q == 0: support_fail += 1; omitted += mass[c]; continue
        Rstar = max(Rstar, t[c] / (Z0 * q)); M2 += H2[c] / q; Xmax = max(Xmax, t[c] / (B * q))
    return dict(log2_B_W0=lg(B), log2_B_over_Z0=lg(B / Z0), log2_R_star=lg(Rstar), log2_M2=lg(M2), max_X_analyzed=fl(Xmax), support_failures=support_fail, omitted_mass_fraction=fl(omitted / Z0) if Z0 > 0 else None, qC=qC, B=B, R_star=Rstar)


def response_moments(qC, cmap, rvals, pf, G, mu):
    """V_j = sum_x p^2 / q (g_j - mu_j)^2 in double (the requested-response second moments; the same definition as dgp2_oracle.lifted_quantities)"""
    qf = np.array([fl(qC.get(c, F(0)) * r_) for c, r_ in zip(cmap, rvals)])
    with np.errstate(divide='ignore', invalid='ignore'): wq = np.where(qf > 0, pf * pf / np.where(qf > 0, qf, 1.0), 0.0)
    Vj = (wq[:, None] * (G - mu[None, :]) ** 2).sum(axis=0); return dict(V_j_max=float(Vj.max()), V_j_median=float(np.median(Vj)), log2_M2_double=float(math.log2(wq.sum())) if wq.sum() > 0 else None)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('model'); ap.add_argument('out'); ap.add_argument('--cap-s', type=float, default=100.0); ap.add_argument('--replay', action='store_true'); ap.add_argument('--replay-draws', type=int, default=1 << 18); ap.add_argument('--seeds', default='1,2,3'); ap.add_argument('--continue', dest='cont', action='store_true'); a = ap.parse_args()
    t_start = tnow(); deadline = t_start + a.cap_s; seeds = [int(x) for x in a.seeds.split(',')]; model, binding = CORE.read_uai(a.model); prev = json.load(open(a.out)) if (a.cont and os.path.exists(a.out)) else {}
    out = dict(model=os.path.abspath(a.model), binding=binding, profile={k: v for k, v in PROFILE.items()}, widths=WIDTHS, cap_s=a.cap_s, replay_requested=a.replay, utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), phases=dict(prev.get('phases') or {}), censored=[], continued_from=(dict(utc=prev.get('utc'), wall_s=prev.get('wall_s'), censored=prev.get('censored')) if prev else None), constructions=dict(prev.get('constructions') or {}), replays=dict(prev.get('replays') or {}))
    def done(k): return k in out['constructions'] and O3.complete_record(out['constructions'][k]) and (out['constructions'][k].get('prepare') != 'READY' or out['constructions'][k].get('log2_B_over_T') is not None)
    clk = CE.Clock(deadline, {}); B = CE.Budget(CE.CONSTRUCTOR_BYTES); M = CE.canonicalize(model, clk, B); n = len(M.cards); assert math.prod(M.cards) <= 1 << 16
    try:
        t0 = tnow(); enum = O2.enumerate_original(M, deadline); out['phases']['enumeration'] = tnow() - t0; Z = enum['Z']; Z0 = Z / M.scalar; out['original'] = dict(Z=str(Z), log2_Z=lg(Z), log2_Z0=lg(Z0), scalar=str(M.scalar), K=len(enum['mu']), n=n, cards=list(M.cards))
        prof, why = CE.slice_profiles(M, clk, B)
        if prof is None: out['note'] = 'proposer unavailable: ' + str(why); raise Deadline('no approximate stage')
        classes = [CE.canonical_classes(CE.farthest_split(prof[v], list(range(M.cards[v])), clk), M.cards[v]) for v in range(n)]; Cz = CE.check_candidate(M, classes, CE.unit_scales(M), clk, B, ratio_product='compact'); rows = LD.build_rows(M, classes, Cz, clk, B); identity = all(len(set(cl)) == len(cl) for cl in classes)
        states = enum['states']; W = enum['W']; cmap = [tuple(classes[v][z[v]] for v in range(n)) for z in states]; rvals = []
        for i, (z, c) in enumerate(zip(states, cmap)):
            if (i & 4095) == 4095 and tnow() >= deadline: raise Deadline('decoder values')
            r_ = F(1)
            for v in range(n): r_ *= F(rows.counts[(v, c[v])][rows.members[v][c[v]].index(z[v])], rows.Q)
            rvals.append(r_)
        t0 = tnow(); t, H2, mass = per_class_reference(enum, M, cmap, rvals, deadline); T = sum(t.values()); out['phases']['reference_t'] = tnow() - t0
        out['reference'] = dict(identity_class_map=identity, coarse_cards=list(Cz.ccards), n_coarse_states=math.prod(Cz.ccards), n_target_classes=len(t), log2_T=lg(T), log2_T_over_Z0=lg(T / Z0), decoder='actual dyadic rows (lifted_decoder.build_rows)', unit='W_0 = canonical target WITHOUT the scalar')
        cstates = list(itertools.product(*[range(k) for k in Cz.ccards])); K = sum(M.cards); Zarr = np.array(states, dtype=np.int64); G = np.zeros((len(states), K)); j = 0
        for v in range(n):
            for a_ in range(M.cards[v]): G[:, j] = (Zarr[:, v] == a_).astype(float); j += 1
        E = max(1, max(w.numerator.bit_length() - w.denominator.bit_length() for w in W if w > 0)) - 60; pf = np.array([float(w / F(2) ** E) if w > 0 else 0.0 for w in W]); pf = pf / pf.sum(); mu = (pf[:, None] * G).sum(axis=0)
        streams = {}; tabs = {}
        for key, env, prof_ in [('G2', 'G2', PROFILE)] + [('RMAX_V%d' % V, 'RMAX', dict(PROFILE, rmax_profile=dict(V=V, fanin=16, mantissa_bits=128))) for V in WIDTHS]:
            if done(key) and not (a.replay and key in ('G2', 'RMAX_V4096') and key not in out['replays']): continue
            if tnow() >= deadline: raise Deadline('construction ' + key)
            t0 = tnow(); S = PA.LiftedStream(2, M, M, [], classes, Cz, 1, EPS, DELTA / 4, dict(prof_, budget_obj=B), envelope=env); r = S.prepare(deadline); prep = tnow() - t0; row = dict(envelope=env, prepare=r, prep_s=prep, stage=S.stage, closed=(S.closed_reason or None), bound_kind=S.bound_kind, rmax=S.mech.get('rmax'), rmax_refusal=S.mech.get('rmax_refusal'), grouped=S.mech.get('grouped_envelope'), mb_splits=(S.mbp.splits if hasattr(S, 'mbp') else None), mb_cap_used=S.mech.get('mb_cap'), memory_policy=S.mech.get('memory_policy'), cap_units=S.mech.get('cap_units'), retained_bytes=S.retained_bytes)
            if r == 'READY':
                lq_ = law_quantities(S, enum, M, t, H2, mass, deadline); row.update({k: v for k, v in lq_.items() if k not in ('qC', 'B', 'R_star')}); ufn = S.upper_weight_fn()
                if env == 'RMAX':
                    sumU = sum(ufn(c) for c in cstates); comp = S.rmax; sumU_compact = sum(comp.U_at(c) for c in cstates)
                    c0 = RM.RMAXCompile(M, classes, Cz, rows, dict(V=comp.V, fanin=16, mantissa_bits=128), B, CE.Clock(deadline, {})); c0.build_sources(); c0.build_seeds(GE.plan_groups(M, Cz, 'G2')[0]); c0.closure(); sumU0 = sum(c0.U_at(c) for c in cstates); c0.release_all()
                    row.update(log2_sumU=lg(sumU), log2_sumU_over_T=lg(sumU / T), log2_sumU_compact_over_T=lg(sumU_compact / T), log2_packing_inflation_sum=lg(sumU / sumU_compact), log2_prefix0_sumU_over_T=lg(sumU0 / T), log2_prefix0_over_completed=lg(sumU0 / sumU_compact), U_ge_t_everywhere=all(ufn(c) >= t[c] for c in t), envelope_valid=RM.enumerate_check_rmax(M, classes, Cz, rows, ufn)['ok'])
                else:
                    Khi = S.rows.K.hi(); sumU = sum(ufn(c) for c in cstates) * Khi / M.scalar                  # G2's retained envelope on t: G_U(c) K_hi (G_U carries the scalar; U is in W_0 units)
                    row.update(log2_sumU=lg(sumU), log2_sumU_over_T=lg(sumU / T), log2_K_hi=lg(Khi), G2_U_ge_t_everywhere=all(ufn(c) * Khi / M.scalar >= t[c] for c in t))
                row.update(log2_B_over_sumU=row['log2_B_W0'] - row['log2_sumU'], log2_B_over_T=row['log2_B_W0'] - lg(T), decomposition_mass=dict(log2_B_over_sumU=row['log2_B_W0'] - row['log2_sumU'], log2_sumU_over_T=row['log2_sumU_over_T']), decomposition_law=dict(log2_B_over_Z0_minus_Rstar=row['log2_B_over_Z0'] - row['log2_R_star'], log2_Rstar_over_T_over_Z0=row['log2_R_star'] - lg(T / Z0)))
                if key in ('G2', 'RMAX_V4096'):
                    row.update(response_moments(lq_['qC'], cmap, rvals, pf, G, mu)); streams[key] = S
                    tabs[key] = dict(classes=classes, qC=lq_['qC'], C_int=lq_['B'] * F(S.scale_F), Ctight=lq_['R_star'] * Z0 * F(S.scale_F), Zint=F(S.scale_F) * Z0, K=S.Kq, Wl=W, states=states, mu=mu)        # the replay tables (dgp2_oracle.replay_lifted shape); C_tight in W_int units = R* Z_int
            out['constructions'][key] = row; print(json.dumps(dict(model=os.path.basename(a.model), construction=key, prepare=r, log2_B_over_T=row.get('log2_B_over_T'), log2_sumU_over_T=row.get('log2_sumU_over_T'), stages=(row.get('rmax') or {}).get('stages_done'), prep_s=round(prep, 2)), default=str), flush=True)
        if a.replay:
            alpha = float(DELTA / 4) / K
            for key in ('G2', 'RMAX_V4096'):
                if key in out['replays'] and O3.complete_record(out['replays'][key]): continue
                if key not in streams: continue
                if tnow() >= deadline: raise Deadline('replay ' + key)
                t0 = tnow(); out['replays'][key] = dict(realized=O2.replay_lifted(streams[key], tabs[key], enum, seeds, a.replay_draws, deadline), seconds=tnow() - t0, note='treatments A current (implemented) cap / B tight cap on the SAME draws; C / D zero allowance (counterfactual)')
            # ---- counterfactual coarse LAWS with the SAME decoder (DGP4 review, section 1 / 2; harness amendment 3): for a law q certified through a RETAINED envelope U the required cap is
            #      B_U(q) = max_c U(c) / q(c) (checked at EVERY coarse assignment: U(c) <= B_U q(c)); sum U is the MINIMUM of that cap over laws (attained by q_U = U / sum U) and is NOT the cap for q_T -- the DGP4
            #      frozen harness replayed q_T under sum U ('required_by_*_sumU_over_Z0'): that column is RELABELLED an oracle-only numerical-cap counterfactual (valid as a target cap since T <= sum U; not certifiable through U)
            laws = {}
            cf_prev = out['replays'].get('counterfactual_laws') or {}; cf_complete = bool(cf_prev) and O3.complete_record(cf_prev) and ('required_by_RMAX_V4096_U' in ((cf_prev.get('q_T_cap_optimal') or {}).get('caps') or {}))
            if not cf_complete:
                for key, env, prof_ in [('G2', 'G2', PROFILE), ('RMAX_V4096', 'RMAX', dict(PROFILE, rmax_profile=dict(V=4096, fanin=16, mantissa_bits=128)))]:     # the retained envelopes U are read from LIVE streams: rebuild deterministically when a --continue run reused the constructions
                    if key not in streams and out['constructions'].get(key, {}).get('prepare') == 'READY':
                        S = PA.LiftedStream(2, M, M, [], classes, Cz, 1, EPS, DELTA / 4, dict(prof_, budget_obj=B), envelope=env)
                        if S.prepare(deadline) == 'READY': streams[key] = S
                eps_num = streams['RMAX_V4096'].eps_num if 'RMAX_V4096' in streams else (streams['G2'].eps_num if 'G2' in streams else 1e-11); W0 = [w / M.scalar for w in W]
                qT = {c: t[c] / T for c in t}; sA = {c: O2.sqrt_up(H2[c]) for c in H2}; sA_sum = sum(sA.values()); q2 = {c: sA[c] / sA_sum for c in sA}        # q_T = t / T (cap-optimal; lemma 5) and q_2 proportional to sqrt(A_c) (second-moment-optimal; lemma R of DGP2)
                Uf = {k: ((streams[k].upper_weight_fn()) if k in streams else None) for k in ('G2', 'RMAX_V4096')}
                def U_of(k, c):
                    S_ = streams[k]; u = Uf[k](c)
                    return (u if k == 'RMAX_V4096' else u * S_.rows.K.hi() / M.scalar)                                 # both in W_0 units (G2's envelope bounds W_0 / d; x K_hi bounds W_0 / r)
                def required_cap(k, q):
                    # B_U(q) = max_c U(c) / q(c) over coarse states with U > 0; a law giving zero mass to a state with positive U cannot be certified through U
                    best = F(0); unsupported = 0
                    for c in cstates:
                        u = U_of(k, c)
                        if u == 0: continue
                        qc = q.get(c, F(0))
                        if qc == 0: unsupported += 1; continue
                        best = max(best, u / qc)
                    return best, unsupported
                def law_rep(name, q):
                    qlog = np.array([lg(q.get(c, F(0)) * r_) if (q.get(c, F(0)) > 0 and r_ > 0) else -np.inf for c, r_ in zip(cmap, rvals)]); Rstar = max(t[c] / (Z0 * q[c]) for c in t if q.get(c, F(0)) > 0); M2 = sum(H2[c] / q[c] for c in H2 if q.get(c, F(0)) > 0)
                    rec = dict(law=name, log2_tight_cap_over_Z0=lg(Rstar), log2_M2=lg(M2), caps={}, checks={})
                    caps = [('tight', lg(Rstar))]
                    for k in ('G2', 'RMAX_V4096'):
                        if k not in streams: continue
                        Bq, uns = required_cap(k, q)
                        if uns: rec['caps']['required_by_%s_U' % k] = dict(not_certifiable='the law gives zero mass to %d coarse states with positive U' % uns); continue
                        rec['checks']['U_le_Bq_%s' % k] = all(U_of(k, c) <= Bq * q.get(c, F(0)) for c in cstates); caps.append(('required_by_%s_U' % k, lg(Bq / Z0)))
                        if k == 'RMAX_V4096' and out['constructions'].get(k, {}).get('log2_sumU') is not None: rec['log2_understatement_of_frozen_sumU_column_bits'] = lg(Bq / Z0) - (out['constructions'][k]['log2_sumU'] - lg(Z0))
                    for capname, caplog in caps:
                        if tnow() >= deadline: rec['caps'][capname] = dict(censored='deadline'); continue
                        rec['caps'][capname] = O3.replay_fine_law(states, W0, Z0, G, mu, qlog, caplog, K, alpha, eps_num, seeds, a.replay_draws, deadline, name + ':' + capname)
                    return rec
                for name, q in (('q_T_cap_optimal', qT), ('q_2_moment_optimal', q2)):
                    if tnow() >= deadline: raise Deadline('counterfactual law ' + name)
                    laws[name] = law_rep(name, q)
                # the checked cap / moment FRONTIER of the retained RMAX envelope (review section 2): for a cap budget C >= sum U, min M2 s.t. q_c >= U_c / C, sum q = 1: q_c = max(U_c / C, lambda sqrt(A_c)); exact diagnostic, not replayed
                if 'RMAX_V4096' in streams and tnow() < deadline:
                    U = {c: U_of('RMAX_V4096', c) for c in cstates}; sumU = sum(U.values()); front = []; pos_sA = [x for x in sA.values() if x > 0]
                    for mult in (1, 2, 4, 8, 16, 64):
                        C = sumU * mult; lo_, hi_ = F(0), (F(1) / min(pos_sA) if pos_sA else F(1))
                        for _ in range(120):
                            lam = (lo_ + hi_) / 2; tot = sum(max(U[c] / C, lam * sA.get(c, F(0))) for c in cstates)
                            if tot > 1: hi_ = lam
                            else: lo_ = lam
                        lam = lo_; q = {c: max(U[c] / C, lam * sA.get(c, F(0))) for c in cstates}; Zq = sum(q.values()); q = {c: v / Zq for c, v in q.items()}
                        Bq = max((U[c] / q[c] for c in cstates if U[c] > 0), default=F(0)); M2 = sum(H2[c] / q[c] for c in H2 if q[c] > 0); Rstar = max(t[c] / (Z0 * q[c]) for c in t if q[c] > 0)
                        front.append(dict(cap_budget_multiple_of_sumU=mult, log2_required_cap_over_Z0=lg(Bq / Z0), log2_tight_cap_over_Z0=lg(Rstar), log2_M2=lg(M2), law_is_U_over_sumU=(mult == 1)))
                    laws['frontier_RMAX_U'] = dict(note='exact diagnostic of the retained RMAX envelope: min M2 at cap budget C = mult x sum U (not replayed; no production construction implied)', points=front)
                out['replays']['counterfactual_laws'] = laws
            if 'ideal_t_over_T' not in out['replays'] or not O3.complete_record(out['replays']['ideal_t_over_T']):
                qlog = np.array([lg((t[c] / T) * r_) if (c in t and r_ > 0) else -np.inf for c, r_ in zip(cmap, rvals)]); eps_num = streams['RMAX_V4096'].eps_num if 'RMAX_V4096' in streams else (streams['G2'].eps_num if 'G2' in streams else 1e-11); W0 = [w / M.scalar for w in W]; rep = dict(label='ideal fixed-decoder law q_C = t / T -- the required_by_*_sumU columns are ORACLE-ONLY numerical-cap counterfactuals (sum U is the minimum cap over laws, attained by U / sum U; T <= sum U makes it a valid TARGET cap for q_T but NOT a cap certifiable through U for q_T; DGP4 review section 1; the certifiable caps are in replays.counterfactual_laws)', caps={})
                for capname, caplog in [('tight_T_over_Z0', lg(T / Z0))] + [('required_by_%s_sumU_over_Z0' % k, out['constructions'][k]['log2_sumU'] - lg(Z0)) for k in ('G2', 'RMAX_V4096') if out['constructions'].get(k, {}).get('log2_sumU') is not None]:
                    if tnow() >= deadline: rep['caps'][capname] = dict(censored='deadline'); continue
                    rep['caps'][capname] = O3.replay_fine_law(states, W0, Z0, G, mu, qlog, caplog, K, alpha, eps_num, seeds, a.replay_draws, deadline, capname)
                out['replays']['ideal_t_over_T'] = rep
    except Deadline as e: out['censored'].append(str(e))
    out['wall_s'] = tnow() - t_start; json.dump(out, open(a.out, 'w'), indent=1, default=str)
    print(json.dumps(dict(model=os.path.basename(a.model), wall=round(out['wall_s'], 2), censored=out['censored'], B_over_T={k: round(v.get('log2_B_over_T'), 2) if v.get('log2_B_over_T') is not None else v.get('prepare') for k, v in out['constructions'].items()}), default=str))


if __name__ == '__main__': main()
