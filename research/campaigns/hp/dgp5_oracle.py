"""DGP5 oracle harness (PROTOCOL.md section 5; brief section 12 'Oracle mechanism panel'): for one <= 2^16-state model -- (1) exact enumeration (dgp2_oracle: W per state, Z, singleton marginals); (2) the production
SEED (joint_proposal.compile_seed at the production profile) and its exact law quantities (R* = max W_0 / q, Z_0, S_0 = sum W_0^2 / q, M2 = S_0 / Z_0^2, max analyzed X); (3) the FIRST attempted family (the production
selection rule: joint_optimize.rank_expansions / choose_retune on the seed with the deterministic interaction scores) and its common bounded coefficient packet at V_coef 4,096 (joint_witness.build_packet; the
retune of the UNCHANGED family is also built); (4) within that one family and packet: the cap-only, moment-only and joint-selected (production score at the fit-derived Z_proxy of a 1,024-draw pilot committed on this
model's seed stream) laws -- each ACTUAL dyadic law with its OWN checked cap / moment; (5) the EXACT coefficients b* / a* by enumeration and the exact-coefficient laws (oracle-assisted counterfactual) plus the oracle-Z
selector (eta = eps Z_0 / 6 with the TRUE Z_0: oracle-assisted); (6) bounded coefficients at volumes 1,024 / 4,096 / 16,384 on the same family (refusals / censoring recorded; only 4,096 is production); (7) --replay: the
accepted certificate replayed for 2^18 draws x seeds 1 / 2 / 3 for the four pinned laws (seed, cap-only, moment-only, joint-selected), each frozen BEFORE any replay draw, with the implemented cap and the exact tight cap
paired on IDENTICAL draws (dgp3_oracle.replay_fine_law shape; one inverse-CDF stream per law); the production trajectory (what the planner would commit over <= 2 attempts) is reported SEPARATELY (not a same-family law
comparison). ORACLE ONLY: exact enumeration, b* / a*, Z_0 never reach production. DGP6 AMENDMENT of this DGP5 replay utility (labelled; the DGP5 scored records are unchanged): the retune / exact-coefficient / oracle-Z comparators rebuild S / H / d / J together (finding 6) and joint_optimize.frontier_laws uses the specified AFFINE C grid (finding 7). usage: dgp5_oracle.py MODEL.uai OUT.json [--cap-s 100] [--replay] [--replay-draws 262144] [--seeds 1,2,3] [--continue]"""

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
import pgm.algorithms.quotient.coarse_envelope as CE, pgm.algorithms.quotient.pac_actions as PA, pgm.algorithms.block.integrated as IG, pgm.algorithms.structural.core as CORE, research.campaigns.hp.dgp2_oracle as O2, research.campaigns.hp.dgp3_oracle as O3
import pgm.algorithms.quotient.joint_proposal as JP, pgm.algorithms.quotient.joint_witness as JW, pgm.algorithms.quotient.joint_optimize as JO, pgm.algorithms.quotient.check_joint as CJ, pgm.algorithms.quotient.joint_stream as JS
from pgm.algorithms.quotient.residual_max_envelope import ZERO, norm_up, from_fraction_up, to_fraction, mul_exact, log2_up
from research.campaigns.hp.dgp2_oracle import EPS, DELTA, CHECKPOINTS, fl, lg, Deadline, tnow
from pgm.algorithms.quotient.unified_pac_planner import PAC_OPTS
VOLUMES = (1024, 4096, 16384); PROF = dict(JP.PROFILE_PRODUCTION)


def law_logq(prop, states):
    n = len(prop.cards); lq = np.zeros(states.shape[0])
    for v in prop.order:
        c = prop.conds[v]; rows = c.row_index(states); lq += np.log2(c.counts[rows, states[:, v]].astype(float))
    return lq - JP.D_BITS * n


def law_record(prop, states, logW0, label, extra=None):
    q = CJ.oracle_law_quantities(prop, states, logW0); rec = dict(label=label, proposal=prop.record()); rec.update({k: (float(v) if isinstance(v, (float, np.floating)) else v) for k, v in q.items()}); rec['log2_witness_S_over_exact_S0'] = prop.log2_S() - q['log2_S0']; rec.update(extra or {}); return rec


def candidate_laws(pk, prop, cards, z, mode, B_cur, S_ref, log2_eta, d_hat_fn, label_prefix=''):
    """every quantized law of the frontier in `mode` with its own witnesses and score; returns (list of candidate dicts with 'prop')"""
    out = []
    for i, (lab, cond, nominal) in enumerate(JO.frontier_laws(pk, prop, cards, PROF, mode, B_cur)):
        if cond is None: out.append(dict(label=label_prefix + lab, rejected=True)); continue
        w = JW.witnesses_of(pk, cond, S_ref=S_ref); conds = dict(prop.conds); conds[z] = cond; newp = JP.Proposal(cards, conds, prop.order, w['B'], w['S'], dict(kind='oracle_candidate', label=lab, mode=mode, nominal_log2_C=nominal)); d = d_hat_fn(newp); H = JO.H_log2(w['log2_S'], w['log2_B'], log2_eta, mode)
        out.append(dict(label=label_prefix + lab, prop=newp, log2_B=w['log2_B'], log2_S=w['log2_S'], S_witness=w['S_witness'], log2_H=H, log2_J=math.log2(d) + H, d_hat=d, nominal_log2_C=nominal, family_volume=cond.family_volume(), index=i + 1, is_current=False))
    return out


def rebuilt(incumbent, S_ref, log2_eta=None, mode='joint'):
    """DGP6 repair (finding 6: oracle objectives -- an amendment of the DGP5 replay utility, labelled): whenever the comparator's moment witness (or eta) changes, S / H / d / J are rebuilt TOGETHER (the frozen DGP5 utility
    replaced log2_S alone and kept the stale log2_J in the retune / exact-coefficient selections)"""
    from pgm.algorithms.quotient.residual_max_envelope import log2_up
    l2 = lambda x: (log2_up(x) if x[1] else -math.inf); inc = dict(incumbent); inc['log2_S'] = l2(S_ref) if not isinstance(S_ref, float) else S_ref; eta = incumbent['log2_eta'] if log2_eta is None else log2_eta; inc['log2_eta'] = eta
    inc['log2_H'] = JO.H_log2(inc['log2_S'], inc['log2_B'], eta, mode); inc['log2_J'] = math.log2(inc['d_hat']) + inc['log2_H']; return inc


def select_from(cands, incumbent):
    win, promoted = JO.select([c for c in cands if 'prop' in c], incumbent, PROF['promotion_margin']); return win, promoted


def exact_packet(M, prop, z, parents, cards, states, logW0):
    """the EXACT coefficient packet (float log2 b* / a* by enumeration) wrapped as a WitnessPacket-like object for the frontier (compact entries from the float log2 values, rounded upward by 1 ulp)"""
    lb, la = CJ.oracle_exact_coefficients(prop, states, logW0, z, parents, cards)
    def comp(l):
        if not np.isfinite(l): return ZERO
        e = int(math.floor(l)) - 127; m = int(math.ceil(2.0 ** (l - math.floor(l)) * (1 << 127) * (1 + 2 ** -50))); return norm_up(e, m)
    b = np.empty(lb.shape, dtype=object); a = np.empty(la.shape, dtype=object)
    for idx in np.ndindex(*lb.shape): b[idx] = comp(lb[idx]); a[idx] = comp(la[idx])
    ctx = prop.conds[z] if tuple(prop.conds[z].parents) == tuple(parents) else prop.conds[z].replicate(tuple(parents), cards)
    pk = JW.WitnessPacket(z, parents, b, a, b, dict(mode='exact', note='oracle-assisted exact b* (float log2 enumeration, rounded up 2^-50 relative)'), dict(mode='exact'), ctx, prop); pk.owned = 0; pk.release = lambda: None; return pk, lb, la


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('model'); ap.add_argument('out'); ap.add_argument('--cap-s', type=float, default=100.0); ap.add_argument('--replay', action='store_true'); ap.add_argument('--replay-draws', type=int, default=1 << 18); ap.add_argument('--seeds', default='1,2,3'); ap.add_argument('--continue', dest='cont', action='store_true'); a = ap.parse_args()
    t_start = tnow(); deadline = t_start + a.cap_s; seeds = [int(x) for x in a.seeds.split(',')]; model, binding = CORE.read_uai(a.model); prev = json.load(open(a.out)) if (a.cont and os.path.exists(a.out)) else {}
    out = dict(model=os.path.abspath(a.model), binding=binding, profile=PROF, volumes=list(VOLUMES), cap_s=a.cap_s, replay_requested=a.replay, utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), phases=dict(prev.get('phases') or {}), censored=[], continued_from=(dict(utc=prev.get('utc'), wall_s=prev.get('wall_s'), censored=prev.get('censored')) if prev else None), replays=dict(prev.get('replays') or {}))
    clk = CE.Clock(deadline, {}); B = CE.Budget(CE.CONSTRUCTOR_BYTES); M = CE.canonicalize(model, clk, B); n = len(M.cards); cards = list(M.cards); assert math.prod(cards) <= 1 << 16
    try:
        t0 = tnow(); enum = O2.enumerate_original(M, deadline); out['phases']['enumeration'] = tnow() - t0; Z = enum['Z']; Z0 = Z / M.scalar; states = np.array(enum['states'], dtype=np.int64); logW0 = CJ.oracle_logW0(M, states); lZ0 = CJ._logsumexp2(logW0)
        out['original'] = dict(Z=str(Z), log2_Z=lg(Z), log2_Z0=lg(Z0), log2_Z0_float_oracle=lZ0, scalar=str(M.scalar), K=len(enum['mu']), n=n, cards=cards, states=int(states.shape[0]))
        K = sum(cards); G = np.zeros((states.shape[0], K)); j = 0
        for v in range(n):
            for a_ in range(cards[v]): G[:, j] = (states[:, v] == a_).astype(float); j += 1
        pf = np.exp2(logW0 - lZ0); mu = (pf[:, None] * G).sum(axis=0); W0_frac = [w / M.scalar for w in enum['W']]
        # ---- (2) the production seed + its exact quantities
        order, vols = CE.elimination_order(cards, [tuple(sc) for sc, _ in M.factors], clk, B); t0 = tnow(); prop_seed, rec_seed, owned = JP.compile_seed(M, order, PROF, B, clk); out['phases']['seed'] = tnow() - t0
        out['seed'] = dict(record={k: v for k, v in rec_seed.items() if k != 'plan'}, law=law_record(prop_seed, states, logW0, 'seed'), exact_check=(CJ.ref_check_law(M, prop_seed) if states.shape[0] <= 4096 else dict(note='exact-rational check restricted to <= 4,096 states; the float oracle quantities are above')))
        if 'exact_check' in out['seed'] and isinstance(out['seed']['exact_check'], dict):
            for k_ in ('Z0', 'Rstar', 'S0'): out['seed']['exact_check'].pop(k_, None)
        # ---- (3) the first attempted family (production rule) + the pilot Z_proxy from the production stream path
        t0 = tnow(); S = JS.JointStream(2, M, M, [], 1, EPS, DELTA / 4, dict(PAC_OPTS, budget_obj=CE.Budget(CE.CONSTRUCTOR_BYTES)), mode='joint', profile=PROF); r = S.prepare(deadline, until=deadline); pil = S.pilot_action(deadline) if r == 'READY' else None; out['phases']['stream_seed_pilot'] = tnow() - t0
        out['stream'] = dict(prepare=r, closed=S.closed_reason, pilot=pil, seed_matches_offline=(r == 'READY' and S.epochs[0].prop.sha256 == prop_seed.sha256), cap_consumed_log2_W0=(S.epochs[0].B_eff_log2 if r == 'READY' else None), eps_num=(S.eps_num if r == 'READY' else None))
        zp = (pil or {}).get('log2_Z_proxy_fit'); d_seed = (pil or {}).get('d_seed_s_per_draw') or 1e-6; log2_eta = math.log2(float(EPS)) + (zp if zp is not None else lZ0) - math.log2(6.0); log2_eta_oracle = math.log2(float(EPS)) + lZ0 - math.log2(6.0)
        out['selector'] = dict(log2_Z_proxy_fit=zp, log2_Z0_true=lZ0, log2_eta_production=log2_eta, log2_eta_oracle_Z=log2_eta_oracle, proxy_error_bits=((zp - lZ0) if zp is not None else None), note='the production selector uses the pilot Z_proxy (heuristic); the oracle-Z selector is a labelled counterfactual')
        pairs, chg = JO.interaction_scores(M, B, clk); exps = JO.rank_expansions(prop_seed, pairs, cards, PROF['V_family']); fam = exps[0] if exps else JO.choose_retune(prop_seed, pairs, cards); z = fam['z']; parents = tuple(fam['new_parents'])
        arity_sum = 2 * n + sum(len(sc) + 1 for sc, _ in M.factors); Kq = K; w0 = prop_seed.work(arity_sum, Kq); d_hat = lambda p_: d_seed * p_.work(arity_sum, Kq) / w0
        out['family'] = dict(z=z, parents=list(parents), expansion=(fam.get('add') is not None), added_variable=fam.get('add'), score=fam.get('score'), ratio=fam.get('ratio'), family_volume=JP.vol_of(parents, cards) * cards[z], whole_model=(len(parents) + 1 == n), ranked=[(e['z'], e['add'], round(e['ratio'], 4), e['volume']) for e in exps[:6]], unchanged_family=dict(z=z, parents=list(prop_seed.conds[z].parents)))
        # ---- (4) the common bounded packet at 4,096 and the three laws within the family; (6) volumes 1,024 / 16,384
        out['packets'] = {}; laws = {}; props = {}
        for V in VOLUMES:
            if tnow() >= deadline: raise Deadline('packet V%d' % V)
            t0 = tnow(); prof = dict(PROF, V_coef=V)
            try:
                pk = JW.build_packet(M, prop_seed, z, parents, order, prof, B, clk, deadline_fn=(lambda: tnow() >= deadline)); b_ref, a_ref = (CJ.ref_coefficients(M, prop_seed, z, parents) if states.shape[0] <= 4096 else (None, None)); wc = CJ.ref_witness_check(pk.b, pk.a, b_ref, a_ref) if b_ref is not None else None
                lb_x, la_x = CJ.oracle_exact_coefficients(prop_seed, states, logW0, z, parents, cards); lb = JO._logs(pk.b); la = JO._logs(pk.a); fin = np.isfinite(lb_x) & np.isfinite(lb)
                rec_pk = dict(V=V, seconds=tnow() - t0, record=pk.record(), exact_rational_check=wc, slack_vs_float_exact=dict(b_max_bits=float((lb - lb_x)[fin].max()) if fin.any() else None, b_median_bits=float(np.median((lb - lb_x)[fin])) if fin.any() else None, a_max_bits=float((la - la_x)[np.isfinite(la_x) & np.isfinite(la)].max()) if (np.isfinite(la_x) & np.isfinite(la)).any() else None, a_mass_bits=(CJ._logsumexp2(la[np.isfinite(la)]) - CJ._logsumexp2(la_x[np.isfinite(la_x)])), b_underbounds=int((lb < lb_x - 1e-9).sum()), a_underbounds=int((la < la_x - 1e-9).sum())), log2_Cmin=(log2_up(pk.Cmin) if pk.Cmin[1] else None))
                inc = JW.witnesses_of(pk, pk.cond_ctx, S_ref=None); B_tight = min(prop_seed.B, inc['B']); S_ref = min([s for s in (prop_seed.S, inc['S']) if s[1]] + [norm_up(*mul_exact(B_tight, B_tight))]); l2 = lambda x: (log2_up(x) if x[1] else -math.inf)
                rec_pk['incumbent'] = dict(log2_B_consumed=prop_seed.log2_B(), log2_B_tight=l2(B_tight), log2_S_ref=l2(S_ref), log2_S_sum_a=inc['log2_S_sum_a'])
                if V == 4096:
                    incumbent = dict(label='seed', is_current=True, log2_B=prop_seed.log2_B(), log2_S=l2(S_ref), log2_eta=log2_eta, log2_H=JO.H_log2(l2(S_ref), prop_seed.log2_B(), log2_eta), family_volume=prop_seed.conds[z].family_volume(), index=-1, d_hat=d_hat(prop_seed)); incumbent['log2_J'] = math.log2(incumbent['d_hat']) + incumbent['log2_H']
                    cj = candidate_laws(pk, prop_seed, cards, z, 'joint', prop_seed.B, S_ref, log2_eta, d_hat); win, prom = select_from(cj, incumbent)
                    cc = candidate_laws(pk, prop_seed, cards, z, 'cap_only', prop_seed.B, S_ref, log2_eta, d_hat); cm = candidate_laws(pk, prop_seed, cards, z, 'moment_only', prop_seed.B, S_ref, log2_eta, d_hat)
                    props['seed'] = prop_seed; props['cap_only'] = next((c['prop'] for c in cc if 'prop' in c), None); props['moment_only'] = next((c['prop'] for c in cm if 'prop' in c), None); props['joint_selected'] = (win['prop'] if prom else prop_seed)
                    # the UNCHANGED-family retune (parents = the seed's parents) within the same packet machinery
                    pk_u = JW.build_packet(M, prop_seed, z, tuple(prop_seed.conds[z].parents), order, prof, B, clk, deadline_fn=(lambda: tnow() >= deadline)) if tuple(prop_seed.conds[z].parents) != parents else pk
                    inc_u = JW.witnesses_of(pk_u, pk_u.cond_ctx, S_ref=None); S_ref_u = min([s for s in (prop_seed.S, inc_u['S']) if s[1]]); cu = candidate_laws(pk_u, prop_seed, cards, z, 'joint', prop_seed.B, S_ref_u, log2_eta, d_hat, 'retune:'); win_u, prom_u = select_from(cu, rebuilt(incumbent, S_ref_u))         # DGP6 repair (finding 6): S / H / J rebuilt together
                    props['retune_selected'] = (win_u['prop'] if prom_u else prop_seed)
                    # the oracle-assisted counterfactuals: exact coefficients on the same family; the oracle-Z selector on the bounded packet
                    pk_x, lb_x2, la_x2 = exact_packet(M, prop_seed, z, parents, cards, states, logW0); inc_x = JW.witnesses_of(pk_x, pk_x.cond_ctx, S_ref=None); S_ref_x = min([s for s in (prop_seed.S, inc_x['S']) if s[1]])
                    cx = candidate_laws(pk_x, prop_seed, cards, z, 'joint', prop_seed.B, S_ref_x, log2_eta, d_hat, 'exact_coef:'); win_x, prom_x = select_from(cx, rebuilt(incumbent, S_ref_x)); props['exact_coef_selected'] = (win_x['prop'] if prom_x else prop_seed)                  # DGP6 repair (finding 6); DGP7 repair R7: the law assignment restored (it had been swallowed by the comment)
                    cz = candidate_laws(pk, prop_seed, cards, z, 'joint', prop_seed.B, S_ref, log2_eta_oracle, d_hat, 'oracleZ:'); incZ = rebuilt(incumbent, S_ref, log2_eta_oracle); win_z, prom_z = select_from(cz, incZ); props['oracleZ_selected'] = (win_z['prop'] if prom_z else prop_seed)
                    rec_pk['selection'] = dict(production=dict(winner=win['label'], promoted=prom, incumbent_log2_J=incumbent['log2_J'], winner_log2_J=win['log2_J'], candidates=[{k: v for k, v in c.items() if k != 'prop'} for c in cj]), cap_only=[{k: v for k, v in c.items() if k != 'prop'} for c in cc], moment_only=[{k: v for k, v in c.items() if k != 'prop'} for c in cm], retune=dict(winner=win_u['label'], promoted=prom_u, family=list(prop_seed.conds[z].parents)), exact_coefficients=dict(winner=win_x['label'], promoted=prom_x), oracle_Z_selector=dict(winner=win_z['label'], promoted=prom_z, log2_eta=log2_eta_oracle))
                    for name, p_ in props.items():
                        if p_ is not None: laws[name] = law_record(p_, states, logW0, name, dict(same_as_seed=(p_.sha256 == prop_seed.sha256), exact_check=({k_: v_ for k_, v_ in CJ.ref_check_law(M, p_).items() if k_ not in ('Z0', 'Rstar', 'S0')} if states.shape[0] <= 4096 else None)))
                    coincident = dict(cap_eq_moment=(props['cap_only'] is not None and props['moment_only'] is not None and props['cap_only'].sha256 == props['moment_only'].sha256), cap_eq_joint=(props['cap_only'] is not None and props['cap_only'].sha256 == props['joint_selected'].sha256), moment_eq_joint=(props['moment_only'] is not None and props['moment_only'].sha256 == props['joint_selected'].sha256), whole_model_family=out['family']['whole_model'])
                    out['laws'] = laws; out['coincidence'] = coincident
                    if pk_u is not pk: pk_u.release()
                pk.release()
            except (JP.RefusedJoint, CE.Refused) as e: rec_pk = dict(V=V, seconds=tnow() - t0, refused=getattr(e, 'kind', type(e).__name__), reason=str(getattr(e, 'reason', e))[:160])
            out['packets']['V%d' % V] = rec_pk; print(json.dumps(dict(model=os.path.basename(a.model), V=V, refused=rec_pk.get('refused'), seconds=round(rec_pk['seconds'], 2), b_slack=(rec_pk.get('slack_vs_float_exact') or {}).get('b_max_bits'), a_mass=(rec_pk.get('slack_vs_float_exact') or {}).get('a_mass_bits')), default=str), flush=True)
        # ---- the production trajectory on this model (<= 2 attempts through the real stream; separately reported)
        if r == 'READY':
            t0 = tnow(); traj = []
            for _ in range(PROF['max_attempts']):
                if not S.can_refine(): break
                att = S.refine_action(deadline, deadline + 1000.0); traj.append({k: v for k, v in att.items() if k not in ('candidates',)})
            out['production_trajectory'] = dict(attempts=traj, epochs=[e.record for e in S.epochs], final_law=law_record(S.epoch.prop, states, logW0, 'production_final') if S.epoch is not None and S.epoch.prop is not None else None, seconds=tnow() - t0, note='what the real stream commits over <= 2 attempts with payback (T_before / T_after against a far horizon here); NOT a same-family law comparison')
        S._close('oracle')
        # ---- (7) replays
        if a.replay and 'laws' in out:
            alpha = float(DELTA / 4) / K; eps_num = out['stream']['eps_num'] or 1e-11
            for name in ('seed', 'cap_only', 'moment_only', 'joint_selected'):
                p_ = props.get(name)
                if p_ is None: out['replays'][name] = dict(not_available=True); continue
                if name in out['replays'] and O3.complete_record(out['replays'][name]): continue
                if tnow() >= deadline: raise Deadline('replay ' + name)
                t0 = tnow(); qlog = law_logq(p_, states); R_star = out['laws'][name]['log2_Rstar'] - lZ0; B_impl = p_.log2_B() + (S.epochs[0].record['constants']['cap_margin'] if S.epochs else 0.0) - lZ0
                rep = dict(law=name, proposal_sha256=p_.sha256, same_as_seed=(p_.sha256 == prop_seed.sha256), log2_cap_implemented_over_Z0=B_impl, log2_cap_tight_over_Z0=R_star, caps={})
                for capname, caplog in (('implemented', B_impl), ('tight', R_star)): rep['caps'][capname] = O3.replay_fine_law(enum['states'], W0_frac, Z0, G, mu, qlog, caplog, K, alpha, eps_num, seeds, a.replay_draws, deadline, name + ':' + capname)
                rep['seconds'] = tnow() - t0; out['replays'][name] = rep; print(json.dumps(dict(model=os.path.basename(a.model), replay=name, worst=[ (rep['caps']['implemented']['seeds'].get(str(s_), {}).get('checkpoints') or [{}])[-1].get('worst_radius') for s_ in seeds], seconds=round(rep['seconds'], 1)), default=str), flush=True)
        B.release(owned + chg)
    except Deadline as e: out['censored'].append(str(e))
    out['wall_s'] = tnow() - t_start; json.dump(out, open(a.out, 'w'), indent=1, default=str)
    print(json.dumps(dict(model=os.path.basename(a.model), wall=round(out['wall_s'], 2), censored=out['censored'], seed_B_over_Rstar=(out.get('seed') or {}).get('law', {}).get('log2_B_over_Rstar'), laws={k: (round(v['log2_Rstar_over_Z0'], 3), round(v['log2_M2'], 3)) for k, v in (out.get('laws') or {}).items()}), default=str))


if __name__ == '__main__': main()
