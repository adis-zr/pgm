"""DGP7 RESIDUAL_JOINT, part 4: the stream adapter (brief sections 2-3, 6-7). ResidualStream = the DGP5 JointStream (ONE accepted IG.Certificate, immutable proposal epochs, checked SUM / MAX seed, 1,024-draw pilot, transactional epoch /
batch commits) whose seed pass carries the residual bank (residual_bank.BankSink: the checked MAX-group slacks rho = P / M retained as immutable atoms inside the retention rule) and whose refinement is the LOCAL residual transaction:
(1) target parents FROZEN per request (G1 = seed graph + <= 1 extra earlier parent per variable; the current parents under residual_only, the law frozen); (2) windows of 2 / 4 consecutive sampling-order variables planned over the live
atoms (residual_local.plan_windows: prefix / touch / volume / atom rules; ranked by retained score over the frozen predicted work; <= 8 fitted per transaction); (3) per window ONE unit admission (float fitting arrays + the kernel's compact
arrays + the candidate counts; inside the 64 MiB branch ceiling, the shared constructor account and the process headroom; the old bank / law stay live until the commit), the floating fit (context weights, water-filled rows, <= 8 sweeps,
exact quantization; residual_joint only), the fitting arrays released BEFORE the independent kernel (check_residual.local_kernel: Fhat from the ACTUAL old conditionals + the immutable atoms, K_ref / K_new / B_ref / B_new, the exact gates
10 B_new <= 11 B_ref and 10 B_new <= 11 initial_seed_cap, the moment record, rho_new with the exact <= 1 proof); (4) selection: a changed-law candidate at (G_new / G_ref)(d_new / d_current) < 0.99 passing both exact gates (the lowest
rank), else a same-law tightening at >= 1 % below the consumed cap (the tightest), else nothing; (5) the transaction: every variable-size object preassembled, ONE authoritative deadline sample, the bounded swap (atoms consumed exactly
once, the replacement atom installed, the version advanced, envelope_B = consumed_B = B_new, the epoch committed through the accepted transactional protocol) -- a failure anywhere leaves law / bank / RNG / certificate / risk unchanged;
(6) <= 2 successful transactions per request; bounded activation (4 x 256 draws, a check after each) after a changed law. The forecast is a scheduling heuristic for window ORDER / SKIPPING only: the first window of an attempt is always
tried when admitted (no blanket forecast veto); the hard clock cuts it typed. Typed refusals never end the request. Nothing floating is published: only the kernel's compact, independently derived B / rho enter an epoch / the bank."""
import math, hashlib, json
from fractions import Fraction as F
import numpy as np
import pac_actions as PA
from pac_actions import StreamRefused, tnow, Deadline, inf, log2
import integrated as IG, coarse_envelope as CE
import joint_proposal as JP, joint_optimize as JO, joint_stream as JS
import global_optimize as GO
import residual_bank as RB, residual_local as RL, check_residual as CR
from residual_max_envelope import ZERO, norm_up, mul_exact, log2_up, to_fraction, ge_exact
RESIDUAL_MODES = ('residual_only', 'residual_joint')
PROFILE_RESIDUAL_STREAM = dict(JP.PROFILE_PRODUCTION, max_attempts=4, max_transactions=RL.PROFILE_RESIDUAL['max_transactions'], activation_batches=4, activation_batch=256, retention_share=RB.RETENTION_SHARE, bank_time_floor_s=0.05, forecast_skip_share=0.90, local=dict(RL.PROFILE_RESIDUAL))


# DGP8 repair (DGP7 review: underestimated workspace): the admitted window workspace is a calibrated model of the ACTUAL simultaneous lifetimes -- the floating fit (index arrays of the region assignments: 8 B x vol x nR for the
# assignment table plus its construction copies, ~16 float arrays of vol) and, AFTER the fit arrays are released, the compact kernel (three object arrays / lists of vol compact pairs at ENTRY_BYTES each, one pointer array of vol per
# atom, the per-cell count / key arrays); the two phases never coexist, so the admission test uses max(fit, kernel) + the candidate counts, and the ledger charges each phase for its own lifetime
WORKSPACE = dict(float_per_cell=8, float_region_arrays=2, float_arrays=16, compact_entry_bytes=JP.ENTRY_BYTES, compact_arrays=3, atom_pointer_bytes=8, index_arrays_per_region_var=1, index_extra_arrays=4, per_atom_fixed=4096, overhead=1 << 16)
def window_workspace_estimate(vol, nR, n_atoms, est_counts):
    """-> (est_float, est_kernel, admitted_total = max(est_float, est_kernel) + est_counts) for a window of vol cells over nR region variables with n_atoms atoms"""
    W = WORKSPACE; est_float = W['float_per_cell'] * vol * (W['float_region_arrays'] * nR + W['float_arrays']) + W['overhead']
    est_kernel = (W['compact_entry_bytes'] * W['compact_arrays'] + W['atom_pointer_bytes'] * n_atoms + 8 * (W['index_arrays_per_region_var'] * nR + W['index_extra_arrays'])) * vol + W['per_atom_fixed'] * n_atoms + W['overhead']
    return est_float, est_kernel, max(est_float, est_kernel) + est_counts
def same_law_window(w, prop, state, cards, order, profile):
    """DGP8 repair (DGP7 review: same-law region mismatch): the SAME-LAW kernel pass needs the region of A + the OLD parents + the atom scopes (the G1 target parents belong to the changed-law pass only); -> the window copy the kernel
    validates (R / C / vol recomputed; the identity stamps kept), or None when the recomputed region exceeds the cap"""
    pos = {v: i for i, v in enumerate(order)}; A = list(w['A']); R = set(A)
    for v in A: R |= set(prop.conds[v].parents)
    for aid in w['atoms']: R |= set(state.atoms[aid].axes)
    Rs = sorted(R, key=lambda x: pos[x]); vol = JP.vol_of(tuple(Rs), cards)
    if vol > w.get('max_vol', profile['max_region']): return None
    return dict(w, R=Rs, C=[x for x in Rs if x not in A], vol=vol, whole_model_region=(len(Rs) == len(cards)), same_law_region=True)
def _l2(x): return (log2_up(x) if x[1] else -inf) if x is not None else None
def _pr(x): return (x[0], str(x[1])) if x is not None else None


class ResidualStream(JS.JointStream):
    OWNED_ATTRS = ('fine_bytes', 'joint_bytes', 'bank_bytes')
    def __init__(self, sid, M_fine, M_par, par_stages, seed, eps, delta_s, opts, label=None, scale_to_original=None, mode='residual_joint', profile=None):
        assert mode in RESIDUAL_MODES, mode
        super().__init__(sid, M_fine, M_par, par_stages, seed, eps, delta_s, opts, label=label or 'residual(%s)' % mode, scale_to_original=scale_to_original, mode='seed', profile=dict(PROFILE_RESIDUAL_STREAM, **(profile or {})))
        self.kind = 'residual'; self.mode = mode; self.bank_bytes = 0; self.state = None; self.sink_record = None; self.target_parents = None; self.graph = None; self.transactions_done = 0; self.promotions = []; self.activation = None; self.activation_pending = False
        self.rng_ctx = np.random.default_rng(np.random.SeedSequence([int(seed), 7701]))                 # the SEPARATE advisory RNG of the context draws (the sampler's RNG is never touched by construction)
        self.mech.update(kind='residual', joint_mode=mode, residual_mode=mode, graph_policy=('law frozen (current parents)' if mode == 'residual_only' else 'G1 frozen per request (alias G0 when no extension is legal)'), bound_kind='target_over_direct_conditional_law (residual envelope W <= envelope_B q prod rho)')
    def stage_features(self, st): return dict(n=self.n_par, entries=sum(len(x['values']) for x in self.model['factors']), K=self.K, kind='residual', mode=self.mode)
    def _drop_owned(self):
        dropped = super()._drop_owned()
        if self.state is not None and self.state.atoms: self.state.atoms.clear(); self.state.owned = 0; dropped.append('residual_bank_atoms')            # the bytes are released through bank_bytes (OWNED_ATTRS), never twice
        if self.state is not None and getattr(self.state, 'law', None) is not None: self.state.law = None; dropped.append('residual_state_law')         # DGP9 repair (original DGP7 finding F4c): the released law is no longer reachable from the bank state (its identity string stays)
        return dropped
    # ---- the DGP5 local refinement is NOT available on this stream
    def refine_action(self, hard, work_end): return dict(status='NOT_APPLICABLE', why='ResidualStream: the DGP5 local refinement is replaced by optimize_action')
    def can_refine(self): return False
    def can_optimize(self):
        return self.stage == 'READY' and not self.all_published() and self.pilot is not None and self.refinement_ended is None and len(self.attempts) < self.profile['max_attempts'] and self.transactions_done < self.profile['max_transactions'] and self.allowance_end is not None and tnow() < self.phase_ends['reserve']
    def can_activate(self): return self.stage == 'READY' and self.activation_pending and not self.all_published()
    # ---- the seed pass with the residual bank attached
    def _j_seed(self, deadline):
        B_ = self.opts.get('budget_obj') or CE.Budget(CE.CONSTRUCTOR_BYTES); clk = CE.Clock(deadline, {}); t0 = tnow(); trace = []; p = self.profile; live0 = B_.live
        A_total = (self.mech.get('allowance') or {}).get('total_s') or max(0.0, (self.allowance_end or tnow()) - tnow()); time_cap = max(p['bank_time_floor_s'], p['retention_share'] * A_total)
        mid = hashlib.sha256(json.dumps([list(self.M_par.cards), [[list(sc), [str(x) for x in v]] for sc, v in self.M_par.factors], [[str(x) for x in ps] for ps in self.M_par.psi]]).encode()).hexdigest()
        self.model_identity = mid; self.state = RB.ResidualState(model_identity=mid, seed_proof_identity=None, law=None, envelope_B=None, consumed_B=None, initial_seed_cap=None, budget=B_)
        sink = RB.BankSink(self.state, clk, time_cap, branch_owned_fn=(lambda: self.joint_bytes + max(0, B_.live - live0)), phase=(t0, deadline))
        try: prop, rec, owned = JP.compile_seed(self.M_par, self.order, self.profile, B_, clk, deadline_fn=(lambda: tnow() >= deadline), trace=trace, sink=sink)
        except BaseException:
            self.state.release_all(); raise
        while owned + self.state.owned > p['owned_cap_bytes'] and self.state.atoms:                                                   # the optional bank never turns a valid seed into a policy refusal
            worst = min(self.state.atoms.values(), key=lambda a: (a.score, -a.aid)); self.state.drop_atom(worst.aid, 'evicted at the seed close: seed + bank exceeded the 64 MiB branch ceiling')
        if owned > p['owned_cap_bytes']: B_.release(owned); self.state.release_all(); raise StreamRefused('MEMORY_POLICY', 'the seed owns %d B > the 64 MiB joint storage cap' % owned)
        proof_id = hashlib.sha256(json.dumps(dict(plan=rec.get('plan_sha256'), checker=rec.get('checker')), sort_keys=True, default=str).encode()).hexdigest(); self.state.bind_seed(prop, proof_id)
        self.joint_bytes += owned; self.bank_bytes = self.state.owned; self.retained_bytes += owned + self.bank_bytes; self.ph['seed'] = tnow() - t0; self.ph['bank_retention'] = sink.spent
        self.mech['seed'] = {k: v for k, v in rec.items() if k != 'plan'}; self.mech['seed']['plan_groups'] = len(rec['plan']); self.seed_prop = prop; self.sink_record = sink.record()
        self.mech['residual_bank'] = dict(self.state.record(), sink=self.sink_record, retention_time_cap_s=time_cap, rule='<= 64 atoms / 131,072 entries / 64 MiB branch; score = -log(mean_uniform rho) / retained bytes (advisory); unit atoms ignored; admitted before materializing; <= %d %% of the allowance; evicted before an ordinary seed allocation could fail' % int(100 * p['retention_share']))
        if rec['zero_U']: self.Z = F(0); self.witness = False; self.stage = 'COMPLETE'; self.mech['terminal'] = 'ZERO_MASS_PROVED_BY_UPPER_MODEL'; return
        self.stage = 'CONTRACTED'
    # ---- ONE bounded residual transaction attempt
    def optimize_action(self, hard, work_end):
        try: return self._optimize_action(hard, work_end)
        except Exception as e:
            import traceback; att = dict(index=len(self.attempts), status='INTERNAL', why=repr(e)[:200], traceback=traceback.format_exc()[-1500:]); self.attempts.append(att); self.refinement_ended = 'internal error in the residual attempt (incumbent kept)'; self.mech['candidate_defect'] = repr(e)[:200]; self.mech['attempts'] = self.attempts; return att
    def _frozen_targets(self, prop, cards, B_, clk):
        p = self.profile
        if self.target_parents is None:
            if self.mode == 'residual_only': self.target_parents = {v: tuple(prop.conds[v].parents) for v in prop.order}; self.graph = dict(label='G0', policy='law frozen: the current parents', alias_G0=True, n_extended=0, parents={int(v): list(prop.conds[v].parents) for v in prop.order})
            else:
                if self.pairs is None: self.pairs, chg = JO.interaction_scores(self.M_par, B_, clk); self.joint_bytes += chg; self.retained_bytes += chg; self.pairs_bytes = chg
                parents, grec = GO.select_g1(prop, self.pairs, cards, p['V_family']); self.target_parents = parents; self.graph = dict(grec, label=('G0' if grec['alias_G0'] else 'G1'), policy='G1 frozen per request from the SEED law', parents={int(v): list(parents[v]) for v in parents})
            self.mech['graph'] = self.graph
        return self.target_parents
    def _optimize_action(self, hard, work_end):
        p = self.profile; lp = p['local']; t0 = tnow(); att = dict(index=len(self.attempts), kind='residual_transaction', mode=self.mode, started_offset_s=(tnow() - self.allowance_start) if self.allowance_start else None, transactions_before=self.transactions_done)
        if self.stage != 'READY': att.update(status='NOT_APPLICABLE', why='stream not READY'); self.attempts.append(att); return att
        if self.refinement_ended is not None or len(self.attempts) >= p['max_attempts'] or self.transactions_done >= p['max_transactions']: att.update(status='ENDED', why=self.refinement_ended or 'attempt / transaction cap'); self.attempts.append(att); return att
        if self.pilot is None: att.update(status='SKIPPED', why='no pilot: the checked seed is kept'); self.refinement_ended = att['why']; self.attempts.append(att); return att
        end = min(hard, self.phase_ends['reserve'])
        if tnow() >= end: att.update(status='REFUSED', kind='ALLOWANCE', why='no construction time left inside the original allowance'); self.refinement_ended = att['why']; self.attempts.append(att); return att
        B_ = self.opts.get('budget_obj') or CE.Budget(CE.CONSTRUCTOR_BYTES); clk = CE.Clock(end, {}); cards = list(self.M_par.cards); inc_ep = self.epoch; prop = inc_ep.prop; st = self.state; T_before = work_end - tnow(); att['T_before_s'] = T_before
        self._work0 = self.epochs[0].prop.work(self.arity_sum, self.Kq) if self.epochs[0].prop is not None else getattr(self, '_work0', prop.work(self.arity_sum, self.Kq))
        live = st.live_atoms(); att['bank'] = dict(version=st.version, live_atoms=len(live), entries=st.entries(), bytes=st.bytes_live(), log2_envelope_B=_l2(st.envelope_B), log2_consumed_B=_l2(st.consumed_B), log2_initial_seed_cap=_l2(st.initial_seed_cap))
        if not live: att.update(status='NO_RESIDUAL_INFORMATION', why='the bank holds no live atom (every checked MAX slack was a unit atom, dropped by the retention rule, or already consumed)'); self.refinement_ended = att['why']; self.attempts.append(att); self.mech['attempts'] = self.attempts; return att
        ws = 0; best = None; best_bytes = 0; windows = []; promoted = False; postcommit_records = None
        try:
            targets = self._frozen_targets(prop, cards, B_, clk); att['graph'] = dict(self.graph, parents=None)
            clk.poll('after target selection')
            wins, excl = RL.plan_windows(st, prop, targets, cards, prop.order, lp); att['windows_planned'] = [dict(A=w['A'], R=w['R'], atoms=w['atoms'], vol=w['vol'], score=w['score'], predicted_work_s=w['predicted_work_s'], whole_model_region=w['whole_model_region']) for w in wins]; att['windows_excluded'] = len(excl); att['windows_excluded_sample'] = excl[:4]
            if not wins: att.update(status='NO_WINDOW', why='no window satisfies the frozen profile (prefix / touch / volume / atom rules)'); self.refinement_ended = att['why']; return att
            seed_over_env = 2.0 ** (_l2(st.initial_seed_cap) - _l2(st.envelope_B)); kappa_seed = lp['cap_margin'] * seed_over_env; fitted = 0
            for w in wins:
                remaining = end - tnow()
                if remaining <= 0: windows.append(dict(A=w['A'], atoms=w['atoms'], status='NOT_STARTED', why='allowance exhausted')); break
                if fitted > 0 and w['predicted_work_s'] > p['forecast_skip_share'] * remaining: windows.append(dict(A=w['A'], atoms=w['atoms'], status='FORECAST_SKIPPED', predicted_work_s=w['predicted_work_s'], remaining_s=remaining, note='scheduling heuristic only (the first admitted window of an attempt is always tried)')); continue
                vol = w['vol']; nR = len(w['R']); A = w['A']; est_counts = sum(JP.COUNT_BYTES * JP.vol_of(tuple(targets[v]), cards) * cards[v] + 256 for v in A); est_float, est_kernel, total = window_workspace_estimate(vol, nR, len(w['atoms']), est_counts)
                wrec = dict(A=A, R=w['R'], C=w['C'], atoms=w['atoms'], vol=vol, whole_model_region=w['whole_model_region'], predicted_work_s=w['predicted_work_s'], admission=dict(float=est_float, kernel=est_kernel, counts=est_counts, total=total, rule='max(fit, kernel) + counts: the fit arrays are released before the kernel (simultaneous lifetimes, DGP7 brief section 7)', branch_live=self.joint_bytes + self.bank_bytes + best_bytes))
                if self.joint_bytes + self.bank_bytes + best_bytes + total > p['owned_cap_bytes']: wrec.update(status='REFUSED', kind='MEMORY_POLICY', why='window workspace %d B + branch %d B > the 64 MiB ceiling' % (total, self.joint_bytes + self.bank_bytes + best_bytes)); windows.append(wrec); continue
                head = CE.USABLE_BYTES - CE.CX.rss_bytes()
                if total > head: wrec.update(status='REFUSED', kind='MEMORY', why='process headroom %d < %d' % (head, total)); windows.append(wrec); continue
                try: ws = B_.charge(est_float + est_counts, 'residual window fitting workspace (%d cells)' % vol)
                except CE.Refused as e: wrec.update(status='REFUSED', kind=e.kind, why=str(e.reason)[:160]); windows.append(wrec); continue
                tw = tnow(); fitted += 1; fit = None; conds_new = None; cand = None; windows.append(wrec); wrec['status'] = 'STARTED'
                try:
                    atoms = [st.atoms[a] for a in w['atoms']]
                    if self.mode == 'residual_joint':
                        fit = RL.fit_window(prop, w, atoms, cards, prop.order, 'auto', self.rng_ctx, kappa_seed, lp, clock=clk, deadline=end); wrec['fit'] = {k: v for k, v in fit.items() if k not in ('conds_new',)}
                        if fit['status'] == 'CANDIDATE' and fit.get('feasible_actual'): conds_new = fit['conds_new']
                    B_.release(est_float); ws -= est_float                                                                                   # the fitting arrays are released BEFORE the trusted check (the fit returns only the counts + scalars)
                    ws += B_.charge(est_kernel, 'residual window kernel workspace (%d cells)' % vol)                                         # the kernel's own lifetime (a refusal here is a typed window refusal: CE.Refused -> the attempt's REFUSED branch)
                    w_use = w if conds_new is not None else (same_law_window(w, prop, st, cards, prop.order, lp) or w)                     # DGP8 repair: the same-law pass validates the region WITHOUT the target-only parents
                    if conds_new is None: wrec['same_law_region'] = dict(R=w_use['R'], vol=w_use['vol'], recomputed=bool(w_use.get('same_law_region')))
                    k = CR.local_kernel(st, w_use, w_use['atoms'], prop.conds, conds_new, cards, prop.order, clk, budget=None, want_rho=True, expected_identity=self.model_identity)
                    wrec['kernel'] = {kk: vv for kk, vv in k.items() if kk not in ('rho_new', 'K_ref', 'K_new', 'B_ref', 'B_new', 'T2_max', 'moment_bound')}
                    if not k['ok']: raise CE.Defect('the independent kernel rejected the window: %s' % k.get('why'))
                    if k.get('zero_target'): wrec['status'] = 'ZERO_TARGET'; att['zero_target'] = True; continue
                    gates = k['gate_ref_ok'] and k['gate_seed_ok']
                    if conds_new is not None:
                        conds_full = dict(prop.conds); conds_full.update(conds_new); newp = JP.Proposal(cards, conds_full, prop.order, k['B_new'], min(norm_up(*mul_exact(k['B_new'], k['B_new'])), k['moment_bound']) if k['moment_bound'][1] else norm_up(*mul_exact(k['B_new'], k['B_new'])), dict(kind='residual_joint_candidate', window=dict(A=A, R=w['R'], atoms=w['atoms']), graph=self.graph['label']), predecessor=inc_ep.index)
                        d_ratio = self._d_hat(newp) / self._d_hat(prop); rank = (fit['G_new_actual'] / fit['G_ref']) * d_ratio if fit['G_ref'] > 0 else inf
                        cand = dict(kind='changed_law', window=wrec, region=list(k['region']), prop=newp, conds_new=conds_new, rho_new=k['rho_new'], B_new=k['B_new'], B_ref=k['B_ref'], moment_bound=k['moment_bound'], rank=rank, d_ratio=d_ratio, gates=gates, promotable=(gates and rank < lp['promote_ratio']), counts_bytes=sum(c.bytes for c in conds_new.values()), atom_bytes=JP.ENTRY_BYTES * int(k['rho_new'].size) + RB.ATOM_META_BYTES, kernel_identity=k['identity'], log2_B_new=k['log2_B_new'], log2_B_ref=k['log2_B_ref'], rows_changed=fit['rows_changed'])
                        wrec.update(status=('PROMOTABLE' if cand['promotable'] else 'NOT_PROMOTABLE'), rank=rank, d_ratio=d_ratio, gates=gates, log2_cap_change_vs_consumed=k['log2_B_new'] - _l2(st.consumed_B))
                    else:
                        tight = ge_exact((st.consumed_B[0], 99 * st.consumed_B[1]), (k['B_ref'][0], 100 * k['B_ref'][1]))                      # 100 B_ref <= 99 consumed_B: >= 1 % tighter EXACTLY
                        conds_full = dict(prop.conds); S_same = min([s for s in (prop.S, norm_up(*mul_exact(k['B_ref'], k['B_ref'])), k['moment_bound']) if s[1]])
                        newp = JP.Proposal(cards, conds_full, prop.order, k['B_ref'], S_same, dict(kind='residual_same_law_tightening', window=dict(A=A, R=list(k['region']), atoms=w['atoms'])), predecessor=inc_ep.index)
                        cand = dict(kind='same_law', window=wrec, region=list(k['region']), prop=newp, conds_new=None, rho_new=k['rho_new'], B_new=k['B_ref'], B_ref=k['B_ref'], moment_bound=k['moment_bound'], rank=1.0, d_ratio=1.0, gates=k['gate_seed_ok'], promotable=(tight and k['gate_seed_ok']), counts_bytes=0, atom_bytes=JP.ENTRY_BYTES * int(k['rho_new'].size) + RB.ATOM_META_BYTES, kernel_identity=k['identity'], log2_B_new=k['log2_B_ref'], log2_B_ref=k['log2_B_ref'], rows_changed=0)
                        wrec.update(status=('PROMOTABLE' if cand['promotable'] else 'NOT_PROMOTABLE'), tighter_than_consumed_1pct=tight, log2_cap_change_vs_consumed=k['log2_B_ref'] - _l2(st.consumed_B), fit_status=(fit or {}).get('status'))
                    wrec['seconds'] = tnow() - tw
                    better = cand['promotable'] and (best is None or (cand['kind'] == 'changed_law' and best['kind'] != 'changed_law') or (cand['kind'] == best['kind'] and ((cand['rank'] < best['rank']) if cand['kind'] == 'changed_law' else ge_exact(best['B_new'], cand['B_new']) and best['B_new'] != cand['B_new'])))
                    if better:
                        if best is not None: B_.release(best_bytes)                                                                           # the previously retained candidate's counts + atom leave the account
                        keep = cand['counts_bytes'] + cand['atom_bytes']; best = cand; best_bytes = keep; ws -= keep                       # the retained candidate keeps its admitted bytes; the rest of the window workspace is released below
                        if ws < 0: B_.charge(-ws, 'retained candidate residue'); ws = 0
                finally:
                    wrec.setdefault('seconds', tnow() - tw)
                    if wrec.get('status') == 'STARTED': wrec['status'] = 'INTERRUPTED'
                    wrec['actual_over_predicted'] = (wrec['seconds'] / w['predicted_work_s']) if w.get('predicted_work_s') else None                    # DGP8 repair (DGP7 review: scheduling calibration): the frozen forecast is checked against the actual window time on every cell
                    if wrec['actual_over_predicted'] is not None and wrec['actual_over_predicted'] > 1.0: att['forecast_underestimates'] = att.get('forecast_underestimates', 0) + 1
                    if ws: B_.release(ws); ws = 0
                clk.poll('after window %s' % (A,))
            att['windows'] = windows; att['windows_fitted'] = fitted
            if best is None:
                att.update(status='KEPT_INCUMBENT', label='no checked candidate promoted under the tested windows / atoms / profile / budget', why=('no window produced a promotable candidate' if windows else 'no window was tried'))
                if fitted and all(w_.get('status') in ('NOT_PROMOTABLE', 'ZERO_TARGET', 'REFUSED', 'FORECAST_SKIPPED', 'NOT_STARTED') for w_ in windows): self.refinement_ended = 'no promotable candidate among the planned windows'
                return att
            # ---- the transaction: preassemble, ONE authoritative deadline sample, bounded swap (a failure leaves law / bank / RNG / certificate / risk unchanged)
            newp = best['prop']; txn = dict(id='txn-%d-%d' % (self.sid, self.transactions_done), kind=best['kind'], window=dict(A=best['window']['A'], R=list(best['region']), atoms=best['window']['atoms'], vol=int(best['rho_new'].size), whole_model_region=(len(best['region']) == len(cards))), atoms=list(best['window']['atoms']), kernel_identity=best['kernel_identity'], log2_B_before=_l2(st.consumed_B), log2_B_after=best['log2_B_new'], log2_B_ref_same_law=best['log2_B_ref'], rank=best['rank'], d_ratio=best['d_ratio'], rows_changed=best['rows_changed'], law_before=prop.sha256, law_after=newp.sha256, epoch_before=inc_ep.index, committed_offset_s=None)
            prov = dict(kind=('residual_replacement_changed_law' if best['kind'] == 'changed_law' else 'residual_replacement_same_law'), transaction=txn['id'], consumed_atoms=list(best['window']['atoms']), region=list(best['region']), active=list(best['window']['A']), kernel_identity=best['kernel_identity'], arithmetic=RB.ARITH_VERSION, inequality='rho_new = (envelope_B / B_new) Fhat / q_new <= 1 proved exactly cellwise; Fhat >= q_old,A prod_J rho_j (upward) from the actual old conditionals + the immutable atoms')
            rho_arr = best['rho_new']; finite = [x for x in rho_arr.reshape(-1) if x[1]]; mean_log2 = (sum(log2_up(x) for x in finite) / rho_arr.size) if finite else -inf; mean_rho = (sum(min(1.0, 2.0 ** log2_up(x)) for x in finite) / rho_arr.size) if finite else 0.0; score = (-math.log(max(mean_rho, 2 ** -1000))) / best['atom_bytes']
            consumed_set = set(best['window']['atoms']); keep = [a_ for a_ in st.live_atoms() if a_.aid not in consumed_set]; new_entries = int(rho_arr.size); evict = []           # DGP8 repair (DGP7 review: over-cap banks): the bank limits hold AFTER the swap
            def over(lst): return (len(lst) + 1 > RB.BANK_MAX_ATOMS) or (sum(a_.entries() for a_ in lst) + new_entries > RB.BANK_MAX_ENTRIES) or (sum(a_.bytes for a_ in lst) + best['atom_bytes'] > RB.BRANCH_CAP_BYTES)
            while keep and over(keep): worst = min(keep, key=lambda a_: (a_.score, -a_.aid)); keep.remove(worst); evict.append(worst.aid)
            if over(keep): raise JP.RefusedJoint('MEMORY_POLICY', 'the replacement atom (%d entries, %d B) cannot fit the bank limits (<= %d atoms / %d entries / %d B) even after evicting every other live atom' % (new_entries, best['atom_bytes'], RB.BANK_MAX_ATOMS, RB.BANK_MAX_ENTRIES, RB.BRANCH_CAP_BYTES))
            for aid_ in evict: st.drop_atom(aid_, 'evicted before %s: the bank limits (<= %d atoms / %d entries / %d B) must hold after the swap' % (txn['id'], RB.BANK_MAX_ATOMS, RB.BANK_MAX_ENTRIES, RB.BRANCH_CAP_BYTES))
            txn['evicted_for_bank_limits'] = evict; self.bank_bytes = st.owned
            shared = newp.bytes - best['counts_bytes']; charged_shared = 0; undo = None
            if tnow() >= end: raise Deadline('residual transaction: the allowance passed after the preassembly (nothing committed)')
            charged_shared = B_.charge(shared, 'residual epoch %d law (shared tables re-charged; the old epoch release balances)' % len(self.epochs)); self.joint_bytes += shared + best['counts_bytes']; self.retained_bytes += shared + best['counts_bytes']
            try:
                undo = st.apply_transaction(txn, newp, tuple(best['region']), rho_arr, best['atom_bytes'], prov, score, mean_log2, best['B_new']); st.owned += best['atom_bytes']; st.ledger.append(('transfer', best['atom_bytes'], 'replacement atom (admitted with the window workspace)'))
                # DGP10 (DGP9 independent review; carried repair contract section 3): EVERY variable-size postcommit diagnostic is assembled HERE, after the swap and BEFORE the commit sample -- the bank record (st.record(): per-atom
                # scopes / scores / transactions), the bank_after summary (live-atom scans) and the consumed-bytes figure the release will free; after the commit only bounded scalar bookkeeping and the <= BANK_MAX_ATOMS array drops run
                freed_prosp = sum(a_.bytes for a_ in st.atoms.values() if a_.consumed and a_.bytes and a_.arr is not None); rec_prosp = st.record(); rec_prosp['owned_bytes'] = st.owned - freed_prosp
                bank_after_prosp = dict(version=st.version, live_atoms=len(st.live_atoms()), entries=st.entries(), bytes=st.bytes_live(), log2_envelope_B=_l2(st.envelope_B), log2_consumed_B=_l2(st.consumed_B))
                ep = self._commit_epoch(newp, 'promoted:%s' % best['kind'], end, B_)
            except BaseException:
                if undo is not None: st.revert_transaction(undo); st.owned -= best['atom_bytes']
                self.joint_bytes -= shared + best['counts_bytes']; self.retained_bytes -= shared + best['counts_bytes']; B_.release(charged_shared); raise
            # DGP9 repair (original DGP7 finding F3, residual commit tail): the transaction's commit time IS the epoch's one authoritative sample (taken inside _commit_epoch before the swap); the tail after it is BOUNDED
            # (release of <= BANK_MAX_ATOMS consumed arrays, scalar bookkeeping); no second timestamp is taken for the commit; the payback diagnostic uses the same sample
            t_commit = ep.committed_at; best_bytes = 0; freed = st.release_consumed(txn['id']); txn['consumed_atoms_released_bytes'] = freed; self.bank_bytes = st.owned; txn['committed_offset_s'] = t_commit - self.allowance_start; txn['epoch_after'] = ep.index; txn['version_after'] = st.version; txn['new_atom'] = undo['new_aid']
            assert freed == freed_prosp, (freed, freed_prosp); postcommit_records = (rec_prosp, bank_after_prosp)                   # the prospective records ARE the post-release state (asserted on the freed bytes)
            self.transactions_done += 1; promoted = True; self.activation_pending = (best['kind'] == 'changed_law'); self.promotions.append(txn); self.mech['promotion'] = txn; self.mech['transactions'] = self.promotions
            att.update(status='PROMOTED', promoted=True, transaction=txn, committed_epoch=ep.index, label=('actual law change' if best['kind'] == 'changed_law' else 'cap-only change (same law)'))
            T_after = work_end - t_commit; att['payback'] = dict(T_before_s=T_before, T_after_s=T_after, construction_seconds=t_commit - t0, d_ratio=best['d_ratio'], rank=best['rank'], note='end-to-end payback is judged by the harness on completions / widths / time; a local proxy win is not a performance win')
        except JP.RefusedJoint as e: att.update(status='REFUSED', kind=e.kind, why=str(e.reason)[:240], label='no checked candidate promoted under the tested windows / atoms / profile / budget')
        except CE.Refused as e: att.update(status='REFUSED', kind=e.kind, why=str(e.reason)[:240], label='no checked candidate promoted under the tested windows / atoms / profile / budget')
        except StreamRefused as e: att.update(status='REFUSED', kind=e.kind, why=str(e.reason)[:240], label='no checked candidate promoted under the tested windows / atoms / profile / budget')
        except (Deadline, IG.Deadline) as e: att.update(status='REFUSED', kind='DEADLINE', why=str(e)[:240], label='no checked candidate promoted under the tested windows / atoms / profile / budget')
        except CE.Defect as e: att.update(status='DEFECT', why=str(e)[:240]); self.mech['candidate_defect'] = str(e)[:200]; self.refinement_ended = 'defect in the residual attempt (incumbent kept)'
        except (ValueError, OverflowError, ZeroDivisionError, FloatingPointError) as e: att.update(status='NUMERIC', why=repr(e)[:240])
        except AssertionError as e: att.update(status='DEFECT', why=str(e)[:240]); self.mech['candidate_defect'] = str(e)[:200]; self.refinement_ended = 'defect in the residual attempt (incumbent kept)'
        finally:
            if ws: B_.release(ws); ws = 0
            if best_bytes and not promoted: B_.release(best_bytes)
            att.setdefault('windows', windows)
            if promoted and postcommit_records is not None: att['bank_after'] = postcommit_records[1]; self.mech['residual_bank'] = dict(postcommit_records[0], sink=self.sink_record)          # DGP10: no bank scan / record after the commit sample
            else: att['bank_after'] = dict(version=st.version, live_atoms=len(st.live_atoms()), entries=st.entries(), bytes=st.bytes_live(), log2_envelope_B=_l2(st.envelope_B), log2_consumed_B=_l2(st.consumed_B)); self.mech['residual_bank'] = dict(st.record(), sink=self.sink_record)
            self.bank_bytes = st.owned
            att['seconds'] = tnow() - t0; att['ended_offset_s'] = (tnow() - self.allowance_start) if self.allowance_start else None; self.attempts.append(att); self.mech['attempts'] = self.attempts; self.mech['refinement_ended'] = self.refinement_ended
            self.measurements.append(dict(kind='joint_action', action='residual_optimize', seconds=att['seconds'], completed=(att.get('status') in ('PROMOTED', 'KEPT_INCUMBENT')), features=dict(status=att.get('status'), promoted=att.get('promoted'), windows=len(windows), mode=self.mode)))
        if self.transactions_done >= p['max_transactions'] and self.refinement_ended is None: self.refinement_ended = 'transaction cap (%d successful transactions per request)' % p['max_transactions']
        return att
    # ---- bounded activation of a changed law (charged to sampling work; recorded separately from construction)
    def activation_action(self, hard):
        p = self.profile; t0 = tnow(); d0 = self.draws; nb = 0; r = None; checks = 0; late_skipped = 0
        if not self.can_activate(): return dict(status='NOT_APPLICABLE')
        while nb < p['activation_batches'] and self.stage == 'READY':
            if tnow() >= hard: break
            r = self.batch(hard, hard, B_override=p['activation_batch']); nb += (r == 'COMMITTED')
            if r != 'COMMITTED': break
            if self.stage == 'READY':
                if tnow() >= hard: late_skipped += 1; break                                                                                    # DGP8 repair (DGP7 review: post-deadline publication): no certificate check (the step that publishes rows) after the action's hard clock
                self.check(); checks += 1
        self.activation_pending = False; act = dict(status=('COMPLETE' if nb == p['activation_batches'] else 'SHORT' if self.stage == 'READY' else 'CLOSED'), batches=nb, draws=self.draws - d0, checks=checks, late_checks_skipped=late_skipped, seconds=tnow() - t0, epoch=(self.epoch.index if self.epoch else None), last=r, cap_draws=p['activation_batches'] * p['activation_batch'], note='bounded activation of the changed law under the accepted epoch protocol: certificate / risk unchanged; charged to sampling work')
        self.activation = act if self.activation is None else dict(act, previous=self.activation); self.mech['activation'] = self.activation; self.measurements.append(dict(kind='joint_action', action='residual_activation', seconds=act['seconds'], completed=(nb == p['activation_batches']), features=dict(batches=nb, draws=self.draws - d0))); return act
    def diagnostics(self):
        d = super().diagnostics(); d['joint'].update(kind='residual', residual_mode=self.mode, graph=self.graph, promotion=self.mech.get('promotion'), transactions=self.promotions, activation=self.activation, bank=(dict(self.state.record(), sink=self.sink_record) if self.state is not None else None), bank_bytes=self.bank_bytes, transactions_done=self.transactions_done); d['residual'] = d['joint']; return d
