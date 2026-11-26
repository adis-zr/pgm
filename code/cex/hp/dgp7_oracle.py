"""DGP7 oracle harness (brief section 9 'Run the oracle mechanism first'; PROTOCOL.md sections 1-3, 5-7): for one <= 2^16-state model -- (1) exact enumeration (dgp2_oracle: W_0 per state, Z_0, true singleton marginals; the floating law
quantities of every law: true R* = max W_0 / q, true S_0 = sum W_0^2 / q, true M2 = S_0 / Z_0^2); (2) the production SEED (joint_proposal.compile_seed, production profile) with the <= 4,096-state exact-rational check; (3) the PRODUCTION
trajectory of a REAL residual_stream.ResidualStream in BOTH modes -- residual_joint (RJ) and residual_only (RO), each on a fresh constructor account, sample seed 1, the optional-role risk delta / 4 -- inside ONE absolute allowance
(--allowance-s, default 3.8 s = the production min(E_rem, 0.20 x 19 s, 4 s)): prepare (seed pass WITH the residual bank) -> pilot -> optimize_action while the stream permits (<= 2 transactions) -> bounded activation after a changed law;
every committed epoch's ACTUAL quantized law is captured with its independently checked cap, its TRUE M2 / R*, the exact identity W_0 <= B q prod rho on <= 4,096 states, the bank record, the transactions (window, atoms consumed,
WHOLE_MODEL_REGION flag, cap before / after) and the attempt records (windows planned / fitted / skipped, kernel seconds); the FINAL law of each mode is a replay law (RJ_final / RO_final; intermediate RJ epochs RJ_epoch_k); (4) the
TEACHER = the ideal law q = p, B = Z_0 (ORACLE ONLY; a reference, never a radius floor); (5) the ORACLE-INJECTED law: the SAME local window machinery run once offline on the seed law + an offline bank with the TRUE target context
weights nu(c) = the exact target marginal of C from the enumeration (instead of the proposal's marginal), quantized exactly and checked by the independent kernel -- labelled 'oracle_injected_true_context', kept apart from production;
(6) the UNIFORM-context negative diagnostic law ('uniform_context_DIAGNOSTIC'); (7) --replay: the accepted certificate replayed for 2^18 draws x seeds 1 / 2 / 3 per law in the FROZEN priority order (seed, RJ_final, RO_final,
ideal_q_eq_p, oracle_injected_true_context, uniform_context_DIAGNOSTIC, then RJ_epoch_k), each law with its OWN implemented cap and the tight cap paired on identical draws (dgp3_oracle.replay_fine_law). The mechanism gate of
PROTOCOL section 1 (M) is evaluated per model: >= 0.5 bits TRUE M2 gain of the final production RJ law over the seed AND checked cap <= 1.10 x the best same-law seed cap (the seed's own cap, any same-law tightening of RJ and the RO
final cap) AND every transaction committed inside the declared allowance AND >= 1 actual changed-law transaction. Identical laws (same sha256) are classified, never dropped. ORACLE ONLY: enumeration, Z_0, ideal and injected laws
never reach production. usage: dgp7_oracle.py MODEL.uai OUT.json [--cap-s 100] [--replay] [--replay-laws LIST] [--replay-draws 262144] [--seeds 1,2,3] [--continue] [--allowance-s 3.8]"""
import sys, os, json, time, math, argparse, itertools, hashlib
from fractions import Fraction as F
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), 'cex', 'newarm')); sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), 'cex', 'blockres'))
import coarse_envelope as CE, pac_actions as PA, integrated as IG, core as CORE, dgp2_oracle as O2, dgp3_oracle as O3
import joint_proposal as JP, joint_optimize as JO, check_joint as CJ
import global_optimize as GO, check_global as CG
import residual_bank as RB, residual_local as RL, check_residual as CR, residual_stream as RS
from residual_max_envelope import ZERO, norm_up, from_fraction_up, to_fraction, mul_exact, log2_up
from dgp2_oracle import EPS, DELTA, CHECKPOINTS, fl, lg, Deadline, tnow
from unified_pac_planner import PAC_OPTS
PROF = dict(RS.PROFILE_RESIDUAL_STREAM); LN2 = math.log(2.0); ALLOWANCE_DEFAULT_S = 3.8
REPLAY_PRIORITY = ['seed', 'RJ_final', 'RO_final', 'ideal_q_eq_p', 'oracle_injected_true_context', 'uniform_context_DIAGNOSTIC']          # frozen (PROTOCOL.md section 5): the first four on every anchor before any extra replay; RJ_epoch_k intermediate laws follow
GATE_GAIN_BITS = 0.5; GATE_CAP_RATIO = 1.10


def law_logq(prop, states):
    n = len(prop.cards); lq = np.zeros(states.shape[0])
    for v in prop.order:
        c = prop.conds[v]; rows = c.row_index(states); lq += np.log2(c.counts[rows, states[:, v]].astype(float))
    return lq - JP.D_BITS * n


def law_record(prop, states, logW0, G, mu, label, extra=None):
    """TRUE (exhaustive floating) quantities of one actual law: log2 R* (true max W_0 / q), log2 S*, log2 M2 = S* / Z_0^2, the checked cap and its slack over R*, the implemented max X"""
    q = CG.float_law_quantities(prop, states, logW0, G, mu); rec = dict(label=label, proposal=prop.record()); rec.update({k: (float(v) if isinstance(v, (float, np.floating)) else v) for k, v in q.items()})
    rec['log2_B_checked'] = prop.log2_B(); rec['log2_B_over_Rstar'] = prop.log2_B() - q['log2_B_star']; rec['cap_dominates_true_Rstar'] = bool(prop.log2_B() >= q['log2_B_star'] - 1e-9); rec['log2_S_over_Sstar'] = prop.log2_S() - q['log2_S_star']; rec['log2_B_over_Z0'] = prop.log2_B() - q['log2_Z0']; rec['max_log2_X_implemented'] = q['log2_B_star'] - prop.log2_B(); rec.update(extra or {}); return rec


def strip_attempt(att):
    """the attempt record without arrays (kernel arrays are already excluded by the stream); keeps windows / fit / kernel summaries"""
    out = {}
    for k, v in att.items():
        if k == 'traceback': out[k] = v[-600:]
        else: out[k] = v
    return out


def run_stream(mode, M, allowance_s, deadline, states, logW0, G, mu, prop_seed, lZ0, small):
    """the REAL ResidualStream in one mode inside ONE absolute allowance; -> (record, laws {name: Proposal}, cap_margins {name: float}, stream)"""
    t0 = tnow(); until = t0 + allowance_s; hard = min(deadline, until)
    S = RS.ResidualStream(2, M, M, [], 1, EPS, DELTA / 4, dict(PAC_OPTS, budget_obj=CE.Budget(CE.CONSTRUCTOR_BYTES)), mode=mode); r = S.prepare(hard, until=until)
    rec = dict(mode=mode, prepare=r, closed=S.closed_reason, allowance_s=allowance_s, allowance_absolute_end_offset_s=allowance_s, t_prep=S.t_prep, phase_times=dict(S.ph), seed_matches_offline=(r == 'READY' and S.epochs[0].prop.sha256 == prop_seed.sha256), cap_consumed_log2_W0=(S.epochs[0].B_eff_log2 if r == 'READY' else None), eps_num=(S.eps_num if r == 'READY' else None),
               bank_after_seed=(S.mech.get('residual_bank')), graph_policy=S.mech.get('graph_policy'))
    laws = {}; margins = {}; epochs = []; identity = {}
    if r != 'READY': rec['note'] = 'the stream did not reach READY inside the allowance: no production law of this mode'; rec['seconds'] = tnow() - t0; return rec, laws, margins, S
    pil = S.pilot_action(hard); rec['pilot'] = pil; attempts = []; activations = []; txn_offsets = []
    while S.stage == 'READY' and S.can_optimize() and tnow() < hard:
        att = S.optimize_action(hard, deadline + 1000.0); attempts.append(strip_attempt(att))
        if att.get('status') == 'PROMOTED':
            ep = S.epoch; name = '%s_epoch_%d' % ('RJ' if mode == 'residual_joint' else 'RO', ep.index); laws[name] = ep.prop; txn_offsets.append((att.get('transaction') or {}).get('committed_offset_s'))
            live = list(S.state.live_atoms()); identity[name] = (CR.ref_envelope_exact(M, ep.prop, live, S.state.envelope_B) if small else dict(note='exact identity check restricted to <= 4,096 states'))
            identity[name].update(live_atoms=len(live), version=S.state.version, log2_envelope_B=(log2_up(S.state.envelope_B) if S.state.envelope_B[1] else -math.inf), log2_consumed_B=(log2_up(S.state.consumed_B) if S.state.consumed_B[1] else -math.inf), transaction_kind=(att.get('transaction') or {}).get('kind'))
            if S.can_activate(): activations.append(S.activation_action(deadline))
    for e in S.epochs: epochs.append({k: v for k, v in e.record.items() if k not in ('widening_parts',)} | dict(draws_n=getattr(e, 'draws_n', 0)))
    final = S.epoch.prop if (S.epoch is not None and S.epoch.prop is not None) else None
    if final is not None:
        fname = 'RJ_final' if mode == 'residual_joint' else 'RO_final'; laws[fname] = final
        for nm, p_ in list(laws.items()):
            try: margins[nm] = S._epoch_constants(p_)['cap_margin']
            except Exception as e: margins[nm] = dict(error=repr(e)[:120])
    rec.update(pilot=pil, attempts=attempts, activations=activations, epochs=epochs, transactions=S.promotions, transactions_done=S.transactions_done, transaction_commit_offsets_s=txn_offsets, inside_allowance=all((o is not None and o <= allowance_s) for o in txn_offsets), refinement_ended=S.refinement_ended, bank_final=(dict(S.state.record(), sink=S.sink_record) if S.state is not None else None), graph=S.graph, identity_after_transactions=identity, draws=S.draws, closed=S.closed_reason, stage=S.stage, seconds=tnow() - t0,
               changed_law_transactions=sum(1 for t in S.promotions if t.get('kind') == 'changed_law'), same_law_transactions=sum(1 for t in S.promotions if t.get('kind') == 'same_law'), final_law_sha256=(final.sha256 if final is not None else None), final_is_seed=(final is not None and final.sha256 == prop_seed.sha256), whole_model_region_transactions=[t.get('window', {}).get('whole_model_region') for t in S.promotions],
               note='the REAL production stream (what the planner commits): seed pass with the bank, pilot, <= 2 residual transactions, bounded activation; construction time counted against ONE absolute allowance')
    return rec, laws, margins, S


def offline_bank(M, order, clk, B, label):
    """the seed pass with a bank attached OFFLINE (no time cap: the oracle's offline laws see every retainable atom); -> (prop_seed, state, sink record)"""
    state = RB.ResidualState(model_identity='oracle:' + label, seed_proof_identity=None, law=None, envelope_B=None, consumed_B=None, initial_seed_cap=None, budget=B); sink = RB.BankSink(state, clk, time_cap_s=1e9)
    prop, rec, owned = JP.compile_seed(M, order, JP.PROFILE_PRODUCTION, B, clk, sink=sink); state.bind_seed(prop, rec.get('plan_sha256')); return prop, state, dict(sink.record(), owned=owned, atoms=len(state.atoms))


def true_context_weights(states, logW0, lZ0, C, cards, asg, rpos):
    """nu(c) = the TRUE target marginal of the context C (from the enumeration), spread over the region assignments by their context key"""
    if not C: return np.ones(asg.shape[0]), dict(mode='empty_context')
    cstr = CE.strides([cards[x] for x in C]); nC = JP.vol_of(tuple(C), cards); key_states = np.zeros(states.shape[0], dtype=np.int64); key_asg = np.zeros(asg.shape[0], dtype=np.int64)
    for j, x in enumerate(C): key_states += states[:, x] * cstr[j]; key_asg += asg[:, rpos[x]] * cstr[j]
    p = np.where(np.isfinite(logW0), np.exp2(logW0 - lZ0), 0.0); dist = np.bincount(key_states, weights=p, minlength=nC); dist = dist / max(dist.sum(), 1e-300)
    return dist[key_asg], dict(mode='ORACLE-INJECTED exact TRUE target marginal of C (enumeration)', N_C=nC, normalization=float(dist.sum()))


def fit_window_with_nu(prop, window, atoms, cards, order, nu, crec, kappa_seed, profile=RL.PROFILE_RESIDUAL):
    """residual_local.fit_window with a PRECOMPUTED context weight vector nu (the production function draws its own weights): the same table, cap, water-filled rows, sweeps and exact quantization"""
    t0 = CE.tnow(); A = list(window['A']); R = list(window['R']); rpos = {x: i for i, x in enumerate(R)}; asg = RL.region_assignments(R, cards); vol = asg.shape[0]; D = JP.D
    logF, lq_old = RL.local_table(prop, window, atoms, cards, asg, rpos); fin = np.isfinite(logF); K_ref_float = float(np.exp((logF - lq_old)[fin]).max()) if fin.any() else 0.0
    kappa_publish = min(profile['cap_margin'] * K_ref_float, kappa_seed); kappa_fit = kappa_publish / (1.0 + profile['fit_reserve']); log_kappa = math.log(max(kappa_fit, 1e-300))
    tp = window['target_parents']; rows = {}; rowidx = {}; stidx = {}
    for v in A:
        cond_t = prop.conds[v] if tuple(prop.conds[v].parents) == tuple(tp[v]) else prop.conds[v].replicate(tuple(tp[v]), cards); rows[v] = cond_t.counts.astype(float) / float(D)
        row = np.zeros(vol, dtype=np.int64)
        for p_ in cond_t.parents: row += asg[:, rpos[p_]] * cond_t.pstrides[p_]
        rowidx[v] = row; stidx[v] = asg[:, rpos[v]]
    def objective(rows_):
        lq = np.zeros(vol)
        for v in A: lq += np.log(np.maximum(rows_[v][rowidx[v], stidx[v]], 1e-300))
        val = np.where(fin, np.exp(2 * logF - lq), 0.0); G = float((nu * val).sum()); K = float(np.exp((logF - lq)[fin]).max()) if fin.any() else 0.0; return G, K
    G_ref, K_ref = objective(rows)
    if K_ref > kappa_fit * (1 + 1e-9): return dict(status='INCUMBENT_INFEASIBLE_UNDER_FIT_CAP', G_ref=G_ref, K_float_ref=K_ref, kappa_fit=kappa_fit, kappa_publish=kappa_publish, context=crec, seconds=CE.tnow() - t0)
    best = dict(rows={v: rows[v].copy() for v in A}, G=G_ref, K=K_ref, sweep=0); cur = {v: rows[v].copy() for v in A}; sweeps_done = 0; progress = True; infeasible_rows = 0; zero_rows = 0
    for sweep in range(profile['sweeps']):
        if not progress: break
        progress = False
        for v in A:
            lq_minus = np.zeros(vol)
            for w in A:
                if w != v: lq_minus += np.log(np.maximum(cur[w][rowidx[w], stidx[w]], 1e-300))
            k = cards[v]; nrows = cur[v].shape[0]; key = rowidx[v] * k + stidx[v]
            coef = np.bincount(key, weights=np.where(fin, nu * np.exp(2 * logF - lq_minus), 0.0), minlength=nrows * k).reshape(nrows, k)
            lb = np.full(nrows * k, 0.0); lbv = np.where(fin, np.exp(logF - lq_minus - log_kappa), 0.0); np.maximum.at(lb, key, lbv); lb = lb.reshape(nrows, k)
            new, winfo = RL.waterfill_rows(coef, lb, cur[v]); infeasible_rows += winfo['infeasible_rows']; zero_rows += winfo['zero_rows']; cur[v] = new
        sweeps_done = sweep + 1; Gc, Kc = objective(cur)
        if math.isfinite(Gc) and Kc <= kappa_fit * (1 + 1e-9) and Gc < best['G'] * (1 - 1e-6): best = dict(rows={v: cur[v].copy() for v in A}, G=Gc, K=Kc, sweep=sweeps_done); progress = True
    if best['sweep'] == 0: return dict(status='NO_IMPROVEMENT', G_ref=G_ref, K_float_ref=K_ref, sweeps=sweeps_done, context=crec, kappa_fit=kappa_fit, kappa_publish=kappa_publish, seconds=CE.tnow() - t0)
    conds_new = {}; changed = 0
    for v in A:
        counts = GO.quantize_rows_exact(best['rows'][v], cards[v]); conds_new[v] = JP.Conditional(v, tuple(tp[v]), counts, cards); base = prop.conds[v] if tuple(prop.conds[v].parents) == tuple(tp[v]) else prop.conds[v].replicate(tuple(tp[v]), cards); changed += int(not np.array_equal(counts, base.counts))
    rows_act = {v: conds_new[v].counts.astype(float) / float(D) for v in A}; G_act, K_act = objective(rows_act)
    return dict(status=('CANDIDATE' if changed else 'QUANTIZED_TO_INCUMBENT'), conds_new=conds_new, rows_changed=changed, G_ref=G_ref, G_new_float=best['G'], G_new_actual=G_act, K_float_ref=K_ref, K_float_new_actual=K_act, kappa_fit=kappa_fit, kappa_publish=kappa_publish, feasible_actual=(K_act <= kappa_publish * (1 + 1e-12)), sweeps=sweeps_done, best_sweep=best['sweep'], infeasible_rows=infeasible_rows, zero_rows=zero_rows, context=crec, proxy_ratio_G=(G_act / G_ref if G_ref > 0 else None), seconds=CE.tnow() - t0)


def offline_law(label, fit, state, window, prop_seed, cards, clk, small, M):
    """the kernel-checked law of one offline fit (window of the seed law): -> (record, Proposal | None)"""
    rec = dict(label=label, window=dict(A=window['A'], R=window['R'], atoms=window['atoms'], vol=window['vol'], whole_model_region=window['whole_model_region']), fit={k: v for k, v in fit.items() if k != 'conds_new'})
    conds_new = fit.get('conds_new') if (fit.get('status') == 'CANDIDATE' and fit.get('feasible_actual')) else None
    if conds_new is None: rec['status'] = 'NO_CANDIDATE (%s)' % fit.get('status'); return rec, None
    k = CR.local_kernel(state, window, window['atoms'], prop_seed.conds, conds_new, cards, prop_seed.order, clk, want_rho=True); rec['kernel'] = {kk: vv for kk, vv in k.items() if kk not in ('rho_new', 'K_ref', 'K_new', 'B_ref', 'B_new', 'T2_max', 'moment_bound')}
    if not k['ok'] or k.get('zero_target'): rec['status'] = 'KERNEL_REJECTED' if not k['ok'] else 'ZERO_TARGET'; return rec, None
    conds = dict(prop_seed.conds); conds.update(conds_new); S_new = min([s for s in (norm_up(*mul_exact(k['B_new'], k['B_new'])), k['moment_bound']) if s[1]])
    newp = JP.Proposal(cards, conds, prop_seed.order, k['B_new'], S_new, dict(kind=label, window=dict(A=window['A'], R=window['R'], atoms=window['atoms'])))
    rec.update(status='LAW', gates=dict(ref=k['gate_ref_ok'], seed=k['gate_seed_ok']), log2_B_new=k['log2_B_new'], log2_B_ref=k['log2_B_ref'], log2_cap_change_vs_seed=k['log2_B_new'] - prop_seed.log2_B())
    if small:
        others = [a for a in state.live_atoms() if a.aid not in window['atoms']]; fake = RB.Atom(10 ** 6, tuple(window['R']), k['rho_new'], dict(kind='oracle_offline'), 0.0, 0.0, 1); rec['identity_after'] = CR.ref_envelope_exact(M, newp, others + [fake], k['B_new'])
    return rec, newp


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('model'); ap.add_argument('out'); ap.add_argument('--cap-s', type=float, default=100.0); ap.add_argument('--replay', action='store_true'); ap.add_argument('--replay-laws', default=None, help='comma list (default: the frozen order + RJ_epoch_k)'); ap.add_argument('--replay-draws', type=int, default=1 << 18); ap.add_argument('--seeds', default='1,2,3'); ap.add_argument('--continue', dest='cont', action='store_true'); ap.add_argument('--allowance-s', type=float, default=ALLOWANCE_DEFAULT_S); a = ap.parse_args()
    t_start = tnow(); deadline = t_start + a.cap_s; seeds = [int(x) for x in a.seeds.split(',')]; model, binding = CORE.read_uai(a.model); prev = json.load(open(a.out)) if (a.cont and os.path.exists(a.out)) else {}
    out = dict(model=os.path.abspath(a.model), model_sha256=hashlib.sha256(open(a.model, 'rb').read()).hexdigest(), binding=binding, profile={k: v for k, v in PROF.items() if not isinstance(v, (list, tuple, dict))}, local_profile={k: v for k, v in RL.PROFILE_RESIDUAL.items() if not isinstance(v, (list, tuple))}, allowance_s=a.allowance_s, cap_s=a.cap_s, replay_requested=a.replay, utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), phases=dict(prev.get('phases') or {}), censored=[],
               continued_from=(dict(utc=prev.get('utc'), wall_s=prev.get('wall_s'), censored=prev.get('censored')) if prev else None), replays=dict(prev.get('replays') or {}), replay_priority=REPLAY_PRIORITY, gate_rule=dict(gain_bits=GATE_GAIN_BITS, cap_ratio=GATE_CAP_RATIO, rule='TRUE oracle M2 gain of the final production RJ law over the seed >= 0.5 bits AND its checked cap <= 1.10 x the best same-law seed cap AND every transaction committed inside the declared allowance AND >= 1 actual changed-law transaction'))
    clk = CE.Clock(deadline, {}); B = CE.Budget(CE.CONSTRUCTOR_BYTES); M = CE.canonicalize(model, clk, B); n = len(M.cards); cards = list(M.cards); assert math.prod(cards) <= 1 << 16
    props = {}; laws = {}; margins = {}; S_rj = None; S_ro = None; owned = 0; chg = 0; small = (math.prod(cards) <= 4096)
    def progress(**kw): print(json.dumps(dict(model=os.path.basename(a.model), **kw), default=str), flush=True)
    try:
        t0 = tnow(); enum = O2.enumerate_original(M, deadline); out['phases']['enumeration'] = tnow() - t0; Z = enum['Z']; Z0 = Z / M.scalar; states = np.array(enum['states'], dtype=np.int64); logW0 = CJ.oracle_logW0(M, states); lZ0 = CJ._logsumexp2(logW0)
        K = sum(cards); G = np.zeros((states.shape[0], K)); j = 0
        for v in range(n):
            for a_ in range(cards[v]): G[:, j] = (states[:, v] == a_).astype(float); j += 1
        pf = np.exp2(logW0 - lZ0); mu = (pf[:, None] * G).sum(axis=0); W0_frac = [w / M.scalar for w in enum['W']]
        out['original'] = dict(Z=str(Z), log2_Z=lg(Z), log2_Z0=lg(Z0), log2_Z0_float_oracle=lZ0, scalar=str(M.scalar), K=K, n=n, cards=cards, states=int(states.shape[0])); progress(phase='enumeration', states=int(states.shape[0]), log2_Z0=lZ0, seconds=round(out['phases']['enumeration'], 2))
        # ---- (2) the production seed (offline, production profile) + the offline bank for the injected / uniform laws
        order, vols = CE.elimination_order(cards, [tuple(sc) for sc, _ in M.factors], clk, B); t0 = tnow(); prop_seed, state_off, sink_off = offline_bank(M, order, clk, B, os.path.basename(a.model)); owned = sink_off['owned']; out['phases']['seed'] = tnow() - t0
        out['seed'] = dict(law=law_record(prop_seed, states, logW0, G, mu, 'seed'), exact_check=({k_: v_ for k_, v_ in CJ.ref_check_law(M, prop_seed).items() if k_ not in ('Z0', 'Rstar', 'S0')} if small else dict(note='exact-rational check restricted to <= 4,096 states; the floating quantities are exhaustive floating diagnostics')),
                           offline_bank=dict(state=state_off.record(), sink=sink_off), identity_seed=(CR.ref_envelope_exact(M, prop_seed, state_off.live_atoms(), prop_seed.B) if small else dict(note='exact identity check restricted to <= 4,096 states')))
        props['seed'] = prop_seed; laws['seed'] = out['seed']['law']; progress(phase='seed', log2_B=prop_seed.log2_B(), log2_Rstar=laws['seed']['log2_B_star'], log2_M2=laws['seed']['log2_M2'], atoms=len(state_off.atoms), seconds=round(out['phases']['seed'], 2))
        # ---- (3) the REAL production streams: residual_joint then residual_only (fresh accounts; the same allowance)
        for mode, key in (('residual_joint', 'stream_rj'), ('residual_only', 'stream_ro')):
            if tnow() >= deadline: raise Deadline('production stream %s' % mode)
            t0 = tnow(); rec, lw, mg, S = run_stream(mode, M, a.allowance_s, deadline, states, logW0, G, mu, prop_seed, lZ0, small); out['phases'][key] = tnow() - t0; out[key] = rec
            if mode == 'residual_joint': S_rj = S
            else: S_ro = S
            for nm, p_ in lw.items():
                props[nm] = p_; margins[nm] = mg.get(nm, 0.0); extra = dict(mode=mode, exact_check=({k_: v_ for k_, v_ in CJ.ref_check_law(M, p_).items() if k_ not in ('Z0', 'Rstar', 'S0')} if small else None), identity=rec['identity_after_transactions'].get(nm), same_as_seed=(p_.sha256 == prop_seed.sha256), log2_cap_change_vs_seed=p_.log2_B() - prop_seed.log2_B())
                laws[nm] = law_record(p_, states, logW0, G, mu, nm, extra); laws[nm]['M2_gain_bits_vs_seed'] = laws['seed']['log2_M2'] - laws[nm]['log2_M2']
            progress(phase=key, prepare=rec.get('prepare'), transactions=rec.get('transactions_done'), changed_law=rec.get('changed_law_transactions'), inside_allowance=rec.get('inside_allowance'), final=(('%.4f' % props[('RJ_final' if mode == 'residual_joint' else 'RO_final')].log2_B()) if ('RJ_final' if mode == 'residual_joint' else 'RO_final') in props else None), seconds=round(out['phases'][key], 2))
        # ---- (4) the teacher: ideal q = p, B = Z_0 (oracle only)
        laws['ideal_q_eq_p'] = dict(label='ideal_q_eq_p', log2_Z0=lZ0, log2_B_star=lZ0, log2_S_star=2 * lZ0, log2_M2=0.0, log2_B_over_Rstar=0.0, log2_B_star_over_Z0=0.0, teacher=True, note='ORACLE-ONLY teacher / certificate floor: q = p exactly (X = 1 on every state), B = Z_0, S_0 = Z_0^2 -> M2 = 1 (log2 0); a reference, never a deployable candidate and never a radius floor')
        # ---- (5, 6) the offline laws on the seed law + offline bank: the ORACLE-INJECTED true-context fit and the UNIFORM-context negative diagnostic (the top-ranked planned window; the production RJ first-transaction window when it is planned offline too)
        out['offline'] = {}
        if tnow() < deadline:
            t0 = tnow()
            try:
                pairs, chg = JO.interaction_scores(M, B, clk); parents1, g1rec = GO.select_g1(prop_seed, pairs, cards, PROF['V_family']); wins, excl = RL.plan_windows(state_off, prop_seed, parents1, cards, prop_seed.order)
                out['offline']['graph'] = dict(g1rec, label=('G0' if g1rec['alias_G0'] else 'G1'), parents={int(v): list(parents1[v]) for v in parents1}); out['offline']['windows_planned'] = [dict(A=w['A'], R=w['R'], atoms=w['atoms'], vol=w['vol'], score=w['score'], whole_model_region=w['whole_model_region']) for w in wins]; out['offline']['windows_excluded'] = len(excl)
                if wins:
                    first_txn = (out.get('stream_rj') or {}).get('transactions') or []; wsel = wins[0]; how = 'top-ranked offline window'
                    if first_txn:
                        tw = first_txn[0].get('window') or {}; match = [w for w in wins if list(w['A']) == list(tw.get('A', [])) and list(w['atoms']) == list(tw.get('atoms', []))]
                        if match: wsel = match[0]; how = 'the production RJ first-transaction window (also planned offline)'
                    out['offline']['window_selection'] = how; seed_over_env = 1.0; kappa_seed = RL.PROFILE_RESIDUAL['cap_margin'] * seed_over_env; atoms_w = [state_off.atoms[x] for x in wsel['atoms']]
                    R_ = list(wsel['R']); C_ = list(wsel['C']); rpos = {x: i for i, x in enumerate(R_)}; asg = RL.region_assignments(R_, cards); nu_true, ctrue = true_context_weights(states, logW0, lZ0, C_, cards, asg, rpos)
                    fit_inj = fit_window_with_nu(prop_seed, wsel, atoms_w, cards, prop_seed.order, nu_true, ctrue, kappa_seed); rec_inj, p_inj = offline_law('oracle_injected_true_context', fit_inj, state_off, wsel, prop_seed, cards, clk, small, M); out['offline']['oracle_injected_true_context'] = rec_inj
                    if p_inj is not None: props['oracle_injected_true_context'] = p_inj; laws['oracle_injected_true_context'] = law_record(p_inj, states, logW0, G, mu, 'oracle_injected_true_context', dict(oracle_injected=True, same_as_seed=(p_inj.sha256 == prop_seed.sha256), log2_cap_change_vs_seed=p_inj.log2_B() - prop_seed.log2_B(), exact_check=({k_: v_ for k_, v_ in CJ.ref_check_law(M, p_inj).items() if k_ not in ('Z0', 'Rstar', 'S0')} if small else None), note='ORACLE-INJECTED: the true target marginal of C replaced the proposal context weights; never a production law')); laws['oracle_injected_true_context']['M2_gain_bits_vs_seed'] = laws['seed']['log2_M2'] - laws['oracle_injected_true_context']['log2_M2']
                    rng_u = np.random.default_rng(np.random.SeedSequence([1, 7701])); fit_u = RL.fit_window(prop_seed, wsel, atoms_w, cards, prop_seed.order, 'uniform', rng_u, kappa_seed, clock=clk); rec_u, p_u = offline_law('uniform_context_DIAGNOSTIC', fit_u, state_off, wsel, prop_seed, cards, clk, small, M); out['offline']['uniform_context_DIAGNOSTIC'] = rec_u
                    if p_u is not None: props['uniform_context_DIAGNOSTIC'] = p_u; laws['uniform_context_DIAGNOSTIC'] = law_record(p_u, states, logW0, G, mu, 'uniform_context_DIAGNOSTIC', dict(negative_diagnostic=True, same_as_seed=(p_u.sha256 == prop_seed.sha256), log2_cap_change_vs_seed=p_u.log2_B() - prop_seed.log2_B(), exact_check=({k_: v_ for k_, v_ in CJ.ref_check_law(M, p_u).items() if k_ not in ('Z0', 'Rstar', 'S0')} if small else None), note='UNIFORM context weights: the labelled negative diagnostic of the context-weight layer')); laws['uniform_context_DIAGNOSTIC']['M2_gain_bits_vs_seed'] = laws['seed']['log2_M2'] - laws['uniform_context_DIAGNOSTIC']['log2_M2']
                    # the production-proposal context fit on the same window (auto mode) for the three-way comparison of the context-weight layer
                    rng_p = np.random.default_rng(np.random.SeedSequence([1, 7701])); fit_p = RL.fit_window(prop_seed, wsel, atoms_w, cards, prop_seed.order, 'auto', rng_p, kappa_seed, clock=clk); rec_p, p_p = offline_law('offline_proposal_context', fit_p, state_off, wsel, prop_seed, cards, clk, small, M); out['offline']['offline_proposal_context'] = rec_p
                    if p_p is not None: props['offline_proposal_context'] = p_p; laws['offline_proposal_context'] = law_record(p_p, states, logW0, G, mu, 'offline_proposal_context', dict(same_as_seed=(p_p.sha256 == prop_seed.sha256), log2_cap_change_vs_seed=p_p.log2_B() - prop_seed.log2_B(), note='the SAME window fitted offline with the production (proposal) context weights: isolates the context-weight error vs the injected law')); laws['offline_proposal_context']['M2_gain_bits_vs_seed'] = laws['seed']['log2_M2'] - laws['offline_proposal_context']['log2_M2']
                else: out['offline']['note'] = 'no window planned offline (no compatible atom)'
                for nm in ('oracle_injected_true_context', 'uniform_context_DIAGNOSTIC', 'offline_proposal_context'):
                    if nm in props and S_rj is not None and S_rj.stage == 'READY':
                        try: margins[nm] = S_rj._epoch_constants(props[nm])['cap_margin']
                        except Exception as e: margins[nm] = 0.0
                    elif nm in props: margins[nm] = 0.0
                out['offline']['seconds'] = tnow() - t0; progress(phase='offline', injected=(laws.get('oracle_injected_true_context') or {}).get('log2_M2'), uniform=(laws.get('uniform_context_DIAGNOSTIC') or {}).get('log2_M2'), proposal_ctx=(laws.get('offline_proposal_context') or {}).get('log2_M2'), window=(wins[0]['A'] if wins else None), seconds=round(out['offline']['seconds'], 2))
            except (JP.RefusedJoint, CE.Refused) as e: out['offline']['refused'] = dict(kind=getattr(e, 'kind', type(e).__name__), reason=str(getattr(e, 'reason', e))[:160], seconds=tnow() - t0)
        # ---- mechanism gate (PROTOCOL section 1 M) for THIS model: the final production RJ law vs the seed; the best same-law cap = min(seed cap, RJ same-law tightenings, RO final cap)
        rj = out.get('stream_rj') or {}; ro = out.get('stream_ro') or {}; same_caps = [('seed', prop_seed.log2_B())]
        if 'RO_final' in props: same_caps.append(('RO_final', props['RO_final'].log2_B()))
        for t in rj.get('transactions') or []:
            if t.get('kind') == 'same_law' and t.get('log2_B_after') is not None: same_caps.append(('RJ_same_law:' + t['id'], t['log2_B_after']))
        best_same = min(same_caps, key=lambda x: x[1]); gate = dict(same_law_caps_log2=same_caps, best_same_law_cap=dict(label=best_same[0], log2_B=best_same[1]))
        if 'RJ_final' in props:
            lf = laws['RJ_final']; gain = laws['seed']['log2_M2'] - lf['log2_M2']; ratio_best = 2.0 ** (props['RJ_final'].log2_B() - best_same[1]); ratio_seed = 2.0 ** (props['RJ_final'].log2_B() - prop_seed.log2_B())
            gate.update(final_law='RJ_final', final_is_seed=rj.get('final_is_seed'), M2_gain_bits=gain, log2_M2_seed=laws['seed']['log2_M2'], log2_M2_final=lf['log2_M2'], cap_ratio_vs_best_same_law=ratio_best, cap_ratio_vs_seed=ratio_seed, inside_allowance=rj.get('inside_allowance'), changed_law_transactions=rj.get('changed_law_transactions'), cap_dominates_true_Rstar=lf.get('cap_dominates_true_Rstar'),
                        gain_ok=(gain >= GATE_GAIN_BITS), cap_ok=(ratio_best <= GATE_CAP_RATIO + 1e-12), passed=bool(gain >= GATE_GAIN_BITS and ratio_best <= GATE_CAP_RATIO + 1e-12 and rj.get('inside_allowance') and (rj.get('changed_law_transactions') or 0) >= 1 and lf.get('cap_dominates_true_Rstar')),
                        per_transaction=[dict(id=t.get('id'), kind=t.get('kind'), log2_B_before=t.get('log2_B_before'), log2_B_after=t.get('log2_B_after'), cap_ratio_vs_seed=(2.0 ** (t['log2_B_after'] - prop_seed.log2_B()) if t.get('log2_B_after') is not None else None), cap_ratio_vs_best_same_law=(2.0 ** (t['log2_B_after'] - best_same[1]) if t.get('log2_B_after') is not None else None), committed_offset_s=t.get('committed_offset_s'), whole_model_region=(t.get('window') or {}).get('whole_model_region'), rows_changed=t.get('rows_changed')) for t in (rj.get('transactions') or [])])
        else: gate.update(final_law=None, passed=False, why=('the RJ stream reached no epoch beyond the seed (%s)' % (rj.get('closed') or rj.get('refinement_ended') or rj.get('prepare'))))
        if 'RO_final' in props: gate['RO'] = dict(log2_M2=laws['RO_final']['log2_M2'], M2_gain_bits=laws['seed']['log2_M2'] - laws['RO_final']['log2_M2'], cap_ratio_vs_seed=2.0 ** (props['RO_final'].log2_B() - prop_seed.log2_B()), transactions=ro.get('transactions_done'), inside_allowance=ro.get('inside_allowance'))
        gate['teacher'] = dict(log2_M2=0.0, M2_gain_bits_vs_seed=laws['seed']['log2_M2'], note='the ideal q = p teacher: the maximal possible gain; a reference only')
        for nm in ('oracle_injected_true_context', 'uniform_context_DIAGNOSTIC', 'offline_proposal_context'):
            if nm in laws: gate[nm] = dict(log2_M2=laws[nm]['log2_M2'], M2_gain_bits_vs_seed=laws[nm]['M2_gain_bits_vs_seed'], cap_ratio_vs_seed=2.0 ** laws[nm]['log2_cap_change_vs_seed'])
        out['mechanism_gate'] = gate; progress(phase='gate', **{k: gate.get(k) for k in ('passed', 'M2_gain_bits', 'cap_ratio_vs_best_same_law', 'inside_allowance', 'changed_law_transactions')})
        # ---- classification
        shas = {k: p_.sha256 for k, p_ in props.items()}; groups = {}
        for k, h in shas.items(): groups.setdefault(h, []).append(k)
        out['classification'] = dict(identical_laws=[v for v in groups.values() if len(v) > 1], whole_model_region=dict(production_rj=rj.get('whole_model_region_transactions'), offline=[(w['A'], w['whole_model_region']) for w in (out['offline'].get('windows_planned') or [])][:8]), laws_recorded=sorted(laws), actual_laws=sorted(props), cap_dominates_true_Rstar={k: v.get('cap_dominates_true_Rstar') for k, v in laws.items() if 'cap_dominates_true_Rstar' in v})
        out['laws'] = laws; out['cap_margins'] = {k: (v if isinstance(v, dict) else float(v)) for k, v in margins.items()}
        # ---- (7) replays in the frozen priority order (each law with its own implemented cap + the tight cap on identical draws)
        if a.replay:
            alpha = float(DELTA / 4) / K; eps_num = (rj.get('eps_num') or 1e-11); inter = sorted([k for k in props if k.startswith('RJ_epoch_') or k.startswith('RO_epoch_')]); want = (a.replay_laws.split(',') if a.replay_laws else REPLAY_PRIORITY + inter)
            for name in want:
                if name in out['replays'] and O3.complete_record(out['replays'][name]): continue
                if name == 'ideal_q_eq_p':
                    if tnow() >= deadline: out['replays'][name] = dict(censored='deadline'); continue
                    t0 = tnow(); qlog = logW0 - lZ0; rep = dict(law=name, ideal=True, teacher=True, log2_cap_implemented_over_Z0=0.0, log2_cap_tight_over_Z0=0.0, caps={})
                    rep['caps']['implemented'] = O3.replay_fine_law(enum['states'], W0_frac, Z0, G, mu, qlog, 0.0, K, alpha, eps_num, seeds, a.replay_draws, deadline, name + ':implemented'); rep['caps']['tight'] = rep['caps']['implemented']; rep['seconds'] = tnow() - t0; out['replays'][name] = rep
                else:
                    p_ = props.get(name)
                    if p_ is None: out['replays'][name] = dict(not_available=True, reason=(laws.get(name) or {}).get('status', 'not constructed (no such law on this model)')); continue
                    if tnow() >= deadline: out['replays'][name] = dict(censored='deadline'); continue
                    t0 = tnow(); qlog = law_logq(p_, states); R_star = laws[name]['log2_B_star'] - lZ0; cm = margins.get(name, 0.0); cm = cm if isinstance(cm, float) else 0.0; B_impl = p_.log2_B() + cm - lZ0
                    rep = dict(law=name, proposal_sha256=p_.sha256, same_as_seed=(p_.sha256 == prop_seed.sha256), log2_cap_implemented_over_Z0=B_impl, log2_cap_tight_over_Z0=R_star, cap_margin=cm, caps={})
                    for capname, caplog in (('implemented', B_impl), ('tight', R_star)): rep['caps'][capname] = O3.replay_fine_law(enum['states'], W0_frac, Z0, G, mu, qlog, caplog, K, alpha, eps_num, seeds, a.replay_draws, deadline, name + ':' + capname)
                    rep['seconds'] = tnow() - t0; out['replays'][name] = rep
                progress(replay=name, worst=([(out['replays'][name].get('caps', {}).get('implemented', {}).get('seeds', {}).get(str(s_), {}).get('checkpoints') or [{}])[-1].get('worst_radius') for s_ in seeds] if out['replays'][name].get('caps') else out['replays'][name]), seconds=round(out['replays'][name].get('seconds') or 0, 1))
    except Deadline as e: out['censored'].append(str(e))
    finally:
        for S in (S_rj, S_ro):
            if S is not None and S.live(): S._close('oracle')
        try:
            if owned + chg: B.release(min(owned + chg, B.live))
        except Exception: pass
    out['wall_s'] = tnow() - t_start; json.dump(out, open(a.out, 'w'), indent=1, default=str)
    print(json.dumps(dict(model=os.path.basename(a.model), wall=round(out['wall_s'], 2), censored=out['censored'], gate={k: out.get('mechanism_gate', {}).get(k) for k in ('passed', 'M2_gain_bits', 'cap_ratio_vs_best_same_law')}, laws={k: (round(v['log2_B_star'] - v['log2_Z0'], 3), round(v['log2_M2'], 3)) for k, v in (out.get('laws') or {}).items() if 'log2_M2' in v and 'log2_Z0' in v}), default=str))


if __name__ == '__main__': main()
