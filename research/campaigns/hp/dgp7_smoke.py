"""DGP7 development smoke test (charged under dgp7_dev; not a control): seed pass with the residual bank attached -> the exact residual identity W_0 <= B_seed q prod rho on every state (<= 4,096 states); window planning; one
floating fit + the independent kernel vs the exact-rational local reference; a same-law kernel pass. usage: dgp7_smoke.py OUT.json"""

# Source-checkout entry point; production imports never traverse research.
if __package__ in (None, ""):
    import sys as _research_sys
    from pathlib import Path as _ResearchPath
    _research_sys.path.insert(0, str(_ResearchPath(__file__).resolve().parents[3]))
from research.bootstrap import activate as _activate_research
_activate_research()
from research.paths import repo_root as _repo_root, runs_root as _runs_root, records_root as _records_root, source_path as _source_path
import sys, os, json, time, math, random
from fractions import Fraction as F
import numpy as np
import pgm.algorithms.quotient.coarse_envelope as CE, research.campaigns.hp.check_dgp as C, pgm.algorithms.quotient.joint_proposal as JP, pgm.algorithms.quotient.joint_optimize as JO, pgm.algorithms.quotient.check_joint as CJ, pgm.algorithms.quotient.global_optimize as GO
import pgm.algorithms.quotient.residual_bank as RB, pgm.algorithms.quotient.residual_local as RL, pgm.algorithms.quotient.check_residual as CR
from pgm.algorithms.quotient.residual_max_envelope import to_fraction, log2_up
out = {}
def stage(model, budget_s=60):
    clk = CE.Clock(time.monotonic() + budget_s, {}); B = CE.Budget(CE.CONSTRUCTOR_BYTES); M = CE.canonicalize(model, clk, B); order, _ = CE.elimination_order(list(M.cards), [tuple(sc) for sc, _ in M.factors], clk, B); return M, order, clk, B
def run(name, model, nu_mode='auto'):
    t0 = time.monotonic(); M, order, clk, B = stage(model); cards = list(M.cards); live0 = B.live
    state = RB.ResidualState(model_identity='smoke:' + name, seed_proof_identity=None, law=None, envelope_B=None, consumed_B=None, initial_seed_cap=None, budget=B); sink = RB.BankSink(state, clk, time_cap_s=5.0)
    prop, rec, owned = JP.compile_seed(M, order, JP.PROFILE_PRODUCTION, B, clk, sink=sink); state.bind_seed(prop, rec['plan_sha256'])
    r = dict(n=len(cards), cards=cards, seed_log2_B=prop.log2_B(), owned_seed=owned, bank=state.record(), sink=sink.record(), live_delta=B.live - live0, ledger_consistent=(B.live - live0 == owned + state.owned))
    atoms = state.live_atoms(); r['atoms'] = [dict(aid=a.aid, axes=list(a.axes), entries=a.entries(), score=a.score, mean_log2=a.mean_log2, stage=a.provenance['stage'], group=a.provenance['group']) for a in atoms]
    if math.prod(cards) <= 4096:
        r['identity_seed'] = CR.ref_envelope_exact(M, prop, atoms, prop.B); r['identity_no_atoms'] = CR.ref_envelope_exact(M, prop, [], prop.B)
    # window planning on G1 targets
    pairs, chg = JO.interaction_scores(M, B, clk); parents1, g1 = GO.select_g1(prop, pairs, cards); wins, excl = RL.plan_windows(state, prop, parents1, cards, prop.order); r['g1'] = dict(alias=g1['alias_G0'], n_extended=g1['n_extended']); r['windows'] = [{k: v for k, v in w.items() if k not in ('rank_key', 'target_parents')} for w in wins]; r['excluded'] = excl[:6]
    rng = np.random.default_rng(7); kappa_seed = RL.PROFILE_RESIDUAL['cap_margin']
    fits = []
    for w in wins[:3]:
        atoms_w = [state.atoms[a] for a in w['atoms']]; fit = RL.fit_window(prop, w, atoms_w, cards, prop.order, nu_mode, rng, kappa_seed, clock=clk); fr = {k: v for k, v in fit.items() if k not in ('conds_new',)}
        conds_new = fit.get('conds_new'); k = CR.local_kernel(state, w, w['atoms'], prop.conds, conds_new, cards, prop.order, clk, budget=B, want_rho=True)
        kr = {kk: (vv if not isinstance(vv, np.ndarray) else 'array(%s)' % (vv.shape,)) for kk, vv in k.items() if kk not in ('K_ref', 'K_new', 'B_ref', 'B_new', 'T2_max', 'moment_bound')}
        if k['ok'] and not k.get('zero_target'):
            ref = CR.ref_local_exact(state, w, w['atoms'], prop.conds, conds_new, cards, prop.order)
            kr['ref'] = dict(log2_K_ref=float(CJ.lg_bounded(ref['K_ref'])) if ref['K_ref'] > 0 else None, log2_K_new=float(CJ.lg_bounded(ref['K_new'])) if ref['K_new'] > 0 else None, log2_T2_max=float(CJ.lg_bounded(ref['T2_max'])) if ref['T2_max'] > 0 else None,
                            K_ref_dominates=(to_fraction(k['K_ref']) >= ref['K_ref']), K_new_dominates=(to_fraction(k['K_new']) >= ref['K_new']), T2_dominates=(to_fraction(k['T2_max']) >= ref['T2_max']))
            # the global identity AFTER the transaction (exact): W <= B_new q_new rho_new prod(others)
            if math.prod(cards) <= 4096:
                conds = dict(prop.conds); conds.update(conds_new or {}); newp = JP.Proposal(cards, conds, prop.order, k['B_new'], k['B_new'], dict(kind='smoke')); others = [a for a in atoms if a.aid not in w['atoms']]
                fake = RB.Atom(999, tuple(w['R']), k['rho_new'], {}, 0.0, 0.0, 1); kr['identity_after'] = CR.ref_envelope_exact(M, newp, others + [fake], k['B_new'])
                kr['identity_after_without_new_atom'] = CR.ref_envelope_exact(M, newp, others, k['B_new'])
        # same-law pass
        k0 = CR.local_kernel(state, w, w['atoms'], prop.conds, None, cards, prop.order, clk, budget=B, want_rho=True); kr['same_law'] = dict(ok=k0['ok'], why=k0.get('why'), log2_K_ref=k0.get('log2_K_ref'), log2_B_ref=k0.get('log2_B_ref'), cells=k0.get('cells'), seconds=k0.get('seconds'))
        fits.append(dict(window=dict(A=w['A'], R=w['R'], atoms=w['atoms'], vol=w['vol']), fit=fr, kernel=kr))
    r['fits'] = fits; r['live_delta_end'] = B.live - live0; r['seconds'] = time.monotonic() - t0; out[name] = r
    print(name, 'atoms', len(atoms), 'identity', json.dumps(r.get('identity_seed')), 'noatoms', json.dumps(r.get('identity_no_atoms')), 'windows', len(wins), round(r['seconds'], 2))
    for f_ in fits: print('   ', f_['window'], f_['fit'].get('status'), 'G', f_['fit'].get('G_ref'), f_['fit'].get('G_new_actual'), 'K', f_['fit'].get('K_float_ref'), f_['fit'].get('K_float_new_actual'), '| kernel', f_['kernel'].get('ok'), f_['kernel'].get('why'), 'log2 B_ref/B_new', f_['kernel'].get('log2_B_ref'), f_['kernel'].get('log2_B_new'), 'gates', f_['kernel'].get('gate_ref_ok'), f_['kernel'].get('gate_seed_ok'), 'ref', json.dumps(f_['kernel'].get('ref')), 'after', json.dumps(f_['kernel'].get('identity_after')), 'ctx', (f_['fit'].get('context') or {}).get('mode'))
run('four_cycle', C._four_cycle())
run('n6_clique', C.load_odev('dg_n6_c4_clique_two')[0])
run('n8_clique', C.load('dg_n8_c4_clique_two')[0])
rng = random.Random(5); run('bin_n10', dict(cards=[2] * 10, factors=[dict(scope=(i, j), values=[F(rng.randint(1, 9), rng.randint(1, 5)) for _ in range(4)]) for i in range(10) for j in range(i + 1, 10) if rng.random() < 0.5] + [dict(scope=(v,), values=[F(rng.randint(1, 7)) for _ in range(2)]) for v in range(10)], evidence={}))
json.dump(out, open(sys.argv[1], 'w'), indent=1, default=str)
