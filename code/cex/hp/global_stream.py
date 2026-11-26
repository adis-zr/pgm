"""DGP6 global construction, part 4: the stream adapter (brief sections 2-4, 4a). GlobalStream = the DGP5 JointStream (ONE accepted IG.Certificate, immutable proposal epochs, checked SUM / MAX seed, 1,024-draw pilot, transactional
epoch / batch commits) with the DGP5 local refinement REPLACED by ONE bounded GLOBAL optimization attempt: (1) graph: G1 = G0 + <= 1 extra earlier-sampled parent per variable (global_optimize.select_g1; alias G0 when nothing is
legal; mode g0_global optimizes G0 itself), rows replicated exactly (admitted); (2) the two structural CircuitPlans (cap: MAX; moment: SUM group 0 / MAX others) built from structure only; (3) admission of the WHOLE workspace
(float tapes of both circuits, L-BFGS-B work arrays by SciPy's allocation formula + a conservative bound, parameter / gradient / bound copies, the compact peak, candidate counts, fingerprint scratch, records) as a unit BEFORE any
allocation, inside the 64 MiB new-owned cap and the process headroom; (4) the checked SAME-LAW reference: the compact circuits at the replicated seed counts, independently certified (check_global.certify) -> B_ref / S_ref on
this graph, a witness-only same-law tighter-cap candidate when B_ref < the consumed cap, and the forecast of the final checked evaluation (refused -> the graph is unavailable, the incumbent stays usable); (5) float optimization
(p = 16 then 64, <= 32 evaluations, counter + clock before every evaluation) inside <= 40 % of the remaining optional interval, then the 17-point probability segment under the original MAX / SUM floating circuits (<= 17 forward
evaluations); (6) ONE actual candidate: the lowest-J segment point quantized exactly, B / S recomputed through the compact circuits from the ACTUAL counts (producer) and independently certified (source binding, inventory, every
contraction, closure, dominance); (7) selection: the actual candidate vs the BEST UNCHANGED-LAW comparator (own tightest cap, the common tightest seed S witness; S / H / d / J rebuilt together) at >= 1 % lower J, else the
witness-only candidate vs the CONSUMED baseline, else the incumbent is kept; (8) the transactional epoch commit (no pending batch; eps_num = max over consumed epochs; old storage released after the references are dropped);
(9) bounded activation: <= 2 batches of 256 draws with a certificate check after each (charged to sampling work; recorded separately). A failed attempt is labelled 'no checked candidate promoted under the tested graph /
circuit / objective / budget' -- never 'no family headroom'. eta = eps Z_proxy / 6 is fixed for the whole request (log form; base-2 -> natural logs converted ONCE at the optimizer interface). Nothing floating is ever published:
the float optimum is advisory; only compact, independently certified B / S enter an epoch."""
import math, hashlib
from fractions import Fraction as F
import numpy as np
import pac_actions as PA
from pac_actions import StreamRefused, tnow, Deadline, inf, log2
import integrated as IG, coarse_envelope as CE
import joint_proposal as JP, joint_optimize as JO, joint_stream as JS
import global_circuit as GC, global_optimize as GO, check_global as CG
from residual_max_envelope import ZERO, norm_up, mul_exact, log2_up, to_fraction
LN2 = math.log(2.0)
GLOBAL_MODES = ('seed', 'global', 'g0_global', 'cap_only', 'moment_only')
PROFILE_GLOBAL = dict(JP.PROFILE_PRODUCTION, max_attempts=1, float_frac=0.40, activation_batches=2, activation_batch=256, lbfgs_maxcor=GO.MAXCOR, lbfgs_hard_total=GO.HARD_TOTAL, segment_points=GO.SEGMENT_POINTS, phases=list(GO.PHASES), check_forecast_factor=2.2,
                      compact_cells_per_s=1200000.0, compact_overhead_s=0.015, quantize_entries_per_s=900000.0, float_cells_per_s=15000000.0)          # FROZEN from the development panel (controls/dev/rates_panel_1.json: cardinalities 2-32; floors below the slowest observed model: 1.28 M checked cells / s on card 32, 947 k quantized entries / s, 15.1 M float cells / s; overhead = the least-squares intercept 14 ms)


def lbfgsb_work_bytes(n, m=GO.MAXCOR):
    """the pinned SciPy 1.10 L-BFGS-B allocation (scipy.optimize._lbfgsb_py): wa = 2 m n + 5 n + 11 m^2 + 8 m doubles, iwa = 3 n int32, x / g / low_bnd / upper_bnd / nbd (4 n doubles + n int32) + SciPy's copies (x0 asarray,
    the Bounds lb / ub arrays, the result x and jac: 5 n doubles) + this optimizer's retained copies (the current t, the best iterate per phase x 2, the cached key + gradient, t_seed, the endpoint: 7 n doubles), x 1.25 conservative"""
    wa = 8 * (2 * m * n + 5 * n + 11 * m * m + 8 * m); iwa = 4 * 3 * n; arrays = 8 * 4 * n + 4 * n + 8 * 5 * n + 8 * 7 * n
    return int(1.25 * (wa + iwa + arrays)) + (64 << 10)


class GlobalStream(JS.JointStream):
    def __init__(self, sid, M_fine, M_par, par_stages, seed, eps, delta_s, opts, label=None, scale_to_original=None, mode='global', profile=None):
        assert mode in GLOBAL_MODES, mode
        super().__init__(sid, M_fine, M_par, par_stages, seed, eps, delta_s, opts, label=label or 'global(%s)' % mode, scale_to_original=scale_to_original, mode='seed', profile=dict(PROFILE_GLOBAL, **(profile or {})))
        self.kind = 'global'; self.mode = mode; self.mech.update(kind='global', joint_mode=mode, global_mode=mode, objective=self.objective_mode(), graph_policy=('G0 (diagnostic)' if mode == 'g0_global' else 'G1 only (alias G0 when no extension is legal)'), bound_kind='target_over_direct_conditional_law (global circuits)')
        self.graph = None; self.candidate = None; self.promotion = None; self.activation = None; self.activation_pending = False
    def objective_mode(self): return 'cap_only' if self.mode == 'cap_only' else 'moment_only' if self.mode == 'moment_only' else 'joint'
    def stage_features(self, st): return dict(n=self.n_par, entries=sum(len(x['values']) for x in self.model['factors']), K=self.K, kind='global', mode=self.mode)
    # ---- the DGP5 local refinement is NOT available on this stream
    def refine_action(self, hard, work_end): return dict(status='NOT_APPLICABLE', why='GlobalStream: the DGP5 local refinement is replaced by optimize_action')
    def can_refine(self): return False
    def can_optimize(self):
        return self.stage == 'READY' and not self.all_published() and self.mode != 'seed' and self.pilot is not None and self.refinement_ended is None and len(self.attempts) < self.profile['max_attempts'] and self.allowance_end is not None and tnow() < self.phase_ends['reserve']
    def can_activate(self): return self.stage == 'READY' and self.activation_pending and not self.all_published()
    # ---- the ONE bounded global optimization attempt
    def optimize_action(self, hard, work_end):
        try: return self._optimize_action(hard, work_end)
        except Exception as e:
            import traceback; att = dict(index=len(self.attempts), status='INTERNAL', why=repr(e)[:200], traceback=traceback.format_exc()[-1500:]); self.attempts.append(att); self.refinement_ended = 'internal error in the global attempt (incumbent kept)'; self.mech['candidate_defect'] = repr(e)[:200]; self.mech['attempts'] = self.attempts; return att
    def _optimize_action(self, hard, work_end):
        p = self.profile; t0 = tnow(); att = dict(index=len(self.attempts), kind='global_optimization', started_offset_s=(tnow() - self.allowance_start) if self.allowance_start else None, graph_policy=self.mech['graph_policy'], objective=self.objective_mode())
        if self.stage != 'READY': att.update(status='NOT_APPLICABLE', why='stream not READY'); self.attempts.append(att); return att
        if self.mode == 'seed': att.update(status='DISABLED', why='seed-only mode'); self.refinement_ended = 'seed-only mode'; self.attempts.append(att); return att
        if self.refinement_ended is not None or len(self.attempts) >= p['max_attempts']: att.update(status='ENDED', why=self.refinement_ended or 'attempt cap'); self.attempts.append(att); return att
        if self.pilot is None or self.pilot.get('log2_Z_proxy_fit') is None: att.update(status='SKIPPED', why='no pilot / no positive Z_proxy: the checked seed is kept, optimization skipped'); self.refinement_ended = att['why']; self.attempts.append(att); return att
        end = min(hard, self.phase_ends['reserve'])
        if tnow() >= end: att.update(status='REFUSED', kind='ALLOWANCE', why='no optimization time left inside the original allowance'); self.refinement_ended = att['why']; self.attempts.append(att); return att
        B_ = self.opts.get('budget_obj') or CE.Budget(CE.CONSTRUCTOR_BYTES); clk = CE.Clock(end, {}); cards = list(self.M_par.cards); inc_ep = self.epoch; prop = inc_ep.prop; T_before = work_end - tnow(); att['T_before_s'] = T_before
        self._work0 = self.epochs[0].prop.work(self.arity_sum, self.Kq) if self.epochs[0].prop is not None else getattr(self, '_work0', prop.work(self.arity_sum, self.Kq))
        log2_eta = math.log2(float(self.eps)) + self.pilot['log2_Z_proxy_fit'] - math.log2(6.0); log_eta = log2_eta * LN2; l2 = lambda x: (log2_up(x) if x[1] else -inf); omode = self.objective_mode()
        att['eta'] = dict(log2_eta=log2_eta, log_eta_natural=log_eta, rule='eta = eps x Z_proxy(fit half) / 6; base-2 logs converted to natural ONCE here')
        workspace = 0; g1_bytes = 0; cand_bytes = 0; promoted = False; witness_only = False; win = None
        try:
            # ---- (1) graph
            if self.pairs is None: self.pairs, chg = JO.interaction_scores(self.M_par, B_, clk); self.joint_bytes += chg; self.retained_bytes += chg; self.pairs_bytes = chg
            if self.mode == 'g0_global': parents = {v: tuple(prop.conds[v].parents) for v in prop.order}; grec = dict(alias_G0=True, extensions=[], n_extended=0, total_entries=sum(prop.conds[v].family_volume() for v in prop.order), policy='G0 diagnostic')
            else: parents, grec = GO.select_g1(prop, self.pairs, cards, p['V_family'])
            graph_label = 'G0' if grec['alias_G0'] else 'G1'; att['graph'] = dict(grec, label=graph_label)
            clk.poll('after graph selection')
            # ---- (2) plans from structure only
            PB, PS = GC.build_plans(self.M_par, prop.order, parents, self.order, V=p['V_coef'], fanin=p['fanin']); att['plans'] = dict(cap=PB.record(), moment=PS.record())
            # ---- (3) admission of the whole workspace as ONE unit before any allocation
            n_params = PB.n_params; g1_entries = grec['total_entries']
            est = dict(float_tapes=PB.float_tape_bytes() + PS.float_tape_bytes(), lbfgsb=lbfgsb_work_bytes(n_params, p['lbfgs_maxcor']), compact_peak=max(PB.compact_peak_bytes(), PS.compact_peak_bytes()), g1_counts=JP.COUNT_BYTES * g1_entries + 256 * len(cards), candidate_counts=JP.COUNT_BYTES * g1_entries + 256 * len(cards), segment_rows=2 * 8 * n_params * 2, fingerprint_scratch=64 << 10, records=256 << 10, source_logs=8 * 2 * (sum(cards) + sum(JP.vol_of(tuple(sc), cards) for sc, _ in self.M_par.factors)))
            total = sum(est.values()); att['admission'] = dict(estimate=est, total_bytes=total, joint_bytes_before=self.joint_bytes, owned_cap_bytes=p['owned_cap_bytes'], constructor_live=B_.live, constructor_cap=B_.cap)
            if self.joint_bytes + total > p['owned_cap_bytes']: raise JP.RefusedJoint('MEMORY_POLICY', 'the global workspace (%d B) + owned %d B exceeds the 64 MiB new-owned cap' % (total, self.joint_bytes))
            head = CE.USABLE_BYTES - CE.CX.rss_bytes()
            if total > head: raise JP.RefusedJoint('MEMORY', 'process headroom %d < %d' % (head, total))
            workspace = B_.charge(total - est['g1_counts'] - est['candidate_counts'], 'global optimization workspace (tapes, L-BFGS-B, compact peak, scratch)')      # counts are charged by their own constructors below
            # the FROZEN pre-forecast of the checked work from the plans' physical cell counts (reference + candidate: producer + certifier on both circuits; quantization by entries) must fit the >= 60 % tail BEFORE any compact work
            remaining0 = end - tnow(); cells_ref = 2 * (PB.work_cells + PB.n_source_cells(cards) + PS.work_cells + PS.n_source_cells(cards)); fore_ref = p['compact_overhead_s'] + cells_ref / p['compact_cells_per_s']; fore_q = g1_entries / p['quantize_entries_per_s']; fore_checked = 2 * fore_ref + fore_q
            att['pre_forecast'] = dict(remaining_s=remaining0, cells_reference=cells_ref, forecast_reference_s=fore_ref, forecast_quantization_s=fore_q, forecast_checked_total_s=fore_checked, tail_s=(1.0 - p['float_frac']) * remaining0, rates=dict(compact_cells_per_s=p['compact_cells_per_s'], quantize_entries_per_s=p['quantize_entries_per_s'], compact_overhead_s=p['compact_overhead_s']), note='frozen rates from the development panel (dgp6_smoke); fixed overhead separated from physical work')
            if fore_checked > (1.0 - p['float_frac']) * remaining0: raise JP.RefusedJoint('FORECAST', 'the forecast checked work (%.3f s) does not fit the reserved tail of %.3f s before any compact evaluation: graph %s unavailable, incumbent usable' % (fore_checked, (1.0 - p['float_frac']) * remaining0, graph_label))
            # ---- (4) the replicated seed on the graph + the checked same-law reference (producer + independent certifier)
            p1 = GO.replicate_graph(prop, parents, cards, budget=B_) if not grec['alias_G0'] else prop; g1_bytes = sum(c.bytes for v, c in p1.conds.items() if c is not prop.conds[v])
            tr0 = tnow(); cB_ref, rB = GC.compact_evaluate(PB, self.M_par, p1, B_, clk); cS_ref, rS = GC.compact_evaluate(PS, self.M_par, p1, B_, clk); certB = CG.certify(PB, self.M_par, p1, cB_ref, clk, budget=B_, graph_sha=PB.sha256); certS = CG.certify(PS, self.M_par, p1, cS_ref, clk, budget=B_, graph_sha=PS.sha256); t_ref = tnow() - tr0
            if not (certB['ok'] and certS['ok']): raise CE.Defect('the independent certifier rejected the same-law reference circuits: %s / %s' % (certB.get('why'), certS.get('why')))
            B_ref = certB['value']; S_ref_g = certS['value']; att['reference'] = dict(seconds=t_ref, producer=dict(log2_B=rB['log2'], log2_S=rS['log2'], cells=rB['cells'] + rS['cells']), certified=dict(log2_B=certB['log2'], log2_S=certS['log2'], identity_B=certB['identity'], identity_S=certS['identity']), consumed=dict(log2_B=prop.log2_B(), log2_S=prop.log2_S()), note='the frozen circuits at the SEED counts on this graph: checked reference values (same law)')
            B_tight = min(prop.B, B_ref); S_ref = min([s for s in (prop.S, S_ref_g) if s[1]] + [norm_up(*mul_exact(B_tight, B_tight))]); d0 = self._d_hat(prop); d1 = self._d_hat(p1)
            inc_consumed = dict(label='seed_consumed_cap', is_current=True, log2_B=l2(prop.B), log2_S=l2(S_ref), log2_H=JO.H_log2(l2(S_ref), l2(prop.B), log2_eta, omode), family_volume=self._work0, index=-1, d_hat=d0); inc_consumed['log2_J'] = math.log2(d0) + inc_consumed['log2_H']
            inc_best = dict(label='seed_best_same_law', is_current=True, log2_B=l2(B_tight), log2_S=l2(S_ref), log2_H=JO.H_log2(l2(S_ref), l2(B_tight), log2_eta, omode), family_volume=self._work0, index=-1, d_hat=d0); inc_best['log2_J'] = math.log2(d0) + inc_best['log2_H']
            att['baselines'] = dict(consumed=inc_consumed, best_same_law=inc_best, B_tight_log2=l2(B_tight), S_ref_log2=l2(S_ref), S_ref_source=('seed S' if S_ref == prop.S else 'graph circuit S at seed counts' if S_ref == S_ref_g else 'B_tight^2'), d_hat_seed=d0, d_hat_graph=d1, work_ratio=d1 / d0 if d0 else None)
            # the forecast of the final checked evaluation (producer + certifier on the candidate ~ the reference evaluation) must fit the >= 60 % reserved tail
            now = tnow(); remaining = end - now; need_check = p['check_forecast_factor'] * t_ref + 0.05; att['forecast'] = dict(remaining_s=remaining, need_check_s=need_check, float_share=p['float_frac'])
            if need_check > (1.0 - p['float_frac']) * remaining: raise JP.RefusedJoint('FORECAST', 'the checked evaluation (%.3f s) does not fit the reserved tail of %.3f s: graph %s unavailable, incumbent usable' % (need_check, (1.0 - p['float_frac']) * remaining, graph_label))
            opt_end = now + min(p['float_frac'] * remaining, remaining - need_check)
            cands = []
            if B_tight < prop.B:                                                                       # the witness-only same-law candidate (the G0 sampler keeps its cheaper work; the cap is a law-only quantity)
                newp_w = JP.Proposal(cards, prop.conds, prop.order, B_tight, S_ref, dict(kind='same_law_tighter_cap', graph=graph_label, certified_B=certB['identity']), predecessor=inc_ep.index); Hw = JO.H_log2(l2(S_ref), l2(B_tight), log2_eta, omode)
                cands.append(dict(label='same_law_tighter_cap', change='witness_only', is_current=False, prop=newp_w, log2_B=l2(B_tight), log2_S=l2(S_ref), log2_H=Hw, log2_J=math.log2(d0) + Hw, family_volume=self._work0, index=0, d_hat=d0))
            # ---- (5) float optimization + segment (advisory)
            FB = GC.FloatCircuit(PB, GC.source_logs(self.M_par, 1), cards); FS = GC.FloatCircuit(PS, GC.source_logs(self.M_par, 2), cards); t_seed = FB.logits_from_counts(p1)
            o0 = GC.objective(FB, FS, t_seed, log_eta, None, omode); att['float_seed'] = dict(log2_B=o0['logB'] / LN2, log2_S=o0['logS'] / LN2, f_hard=o0['f'] / LN2, note='float log2 values at the seed logits under the ORIGINAL hard-MAX circuits (advisory)')
            opt = GO.BoundedLBFGS(FB, FS, log_eta, omode, opt_end, p['lbfgs_hard_total']); t_opt0 = tnow(); endpoint, phases = opt.run(t_seed); att['optimizer'] = dict(seconds=tnow() - t_opt0, evaluations=opt.evals, cache_hits=opt.cache_hits, hard_total=p['lbfgs_hard_total'], phases=phases, trace=opt.trace[:64], endpoint=({k: v for k, v in endpoint.items() if k != 't'} if endpoint else None), convention='an evaluation = one joint forward / reverse of BOTH circuits; cached identical requests are served without evaluating and counted as cache_hits; the counter and the clock are checked before every evaluation', note='floating, advisory; the box gap is a diagnostic of the compiled objective, never a proof')
            best = None
            if endpoint is None: att['optimizer_failure'] = 'OPTIMIZER: no completely formed finite iterate before the float cutoff (only the unchanged seed and its witness-only improvement remain in the selection)'
            else:
                seg, best, (rows_seed, rows_opt) = GO.segment_scores(FB, FS, t_seed, endpoint['t'], log_eta, math.log(d1), omode, opt_end, p['segment_points']); att['segment'] = dict(points=seg, best=best, note='forward-only scores under the ORIGINAL MAX / SUM floating circuits with the same eta and the graph d_hat; lambda = 0 is the replicated seed law (not a new law); both the floating and the checked cap are recorded')
                if best is None: att['optimizer_failure'] = 'SEGMENT: no finite segment point inside the float cutoff'
            # ---- (6) ONE actual candidate: the lowest-J segment point (lambda > 0) quantized exactly, B / S through the compact circuits from the ACTUAL counts, independently certified
            if best is not None and best['lam'] > 0:
                clk.poll('before quantization'); tq = tnow(); conds = GO.quantize_segment(FB, rows_seed, rows_opt, best['lam'], cards, prop.order, parents, budget=B_, clock=clk); cand_bytes = sum(c.bytes for c in conds.values())
                newp = JP.Proposal(cards, conds, prop.order, ZERO, ZERO, dict(kind='global_candidate', graph=graph_label, lam=best['lam'], segment_index=best['i']), predecessor=inc_ep.index)
                same_law = all(np.array_equal(conds[v].counts, p1.conds[v].counts) for v in prop.order); att['quantization'] = dict(seconds=tnow() - tq, lam=best['lam'], identical_to_seed=same_law, rule='exact normalization of the binary64 row; 1 + floor((D - k) p_a) exactly; residual by stable state id', bytes=cand_bytes)
                if same_law: raise JP.RefusedJoint('SAME_LAW', 'the quantized segment point reproduces the seed counts: not a new law')
                tc = tnow(); cB, rB2 = GC.compact_evaluate(PB, self.M_par, newp, B_, clk); cS, rS2 = GC.compact_evaluate(PS, self.M_par, newp, B_, clk); kB = CG.certify(PB, self.M_par, newp, cB, clk, budget=B_, graph_sha=PB.sha256); kS = CG.certify(PS, self.M_par, newp, cS, clk, budget=B_, graph_sha=PS.sha256)
                att['certification'] = dict(seconds=tnow() - tc, producer=dict(log2_B=rB2['log2'], log2_S=rS2['log2']), certifier=dict(B_ok=kB['ok'], S_ok=kS['ok'], log2_B=kB.get('log2'), log2_S=kS.get('log2'), why_B=kB.get('why'), why_S=kS.get('why'), identity_B=kB.get('identity'), identity_S=kS.get('identity'), roles=kB.get('roles')), float_at_lambda=dict(log2_B=best['logB'] / LN2, log2_S=best['logS'] / LN2))
                if not (kB['ok'] and kS['ok']): raise CE.Defect('the independent certifier rejected the candidate circuits: %s / %s' % (kB.get('why'), kS.get('why')))
                newp.B = kB['value']; newp.S = min(kS['value'], norm_up(*mul_exact(kB['value'], kB['value']))); newp.sha256 = hashlib.sha256(repr((newp.order, [(v, newp.conds[v].sha256) for v in newp.order], newp.B, newp.S)).encode()).hexdigest()
                dc = self._d_hat(newp); Hc = JO.H_log2(l2(newp.S), l2(newp.B), log2_eta, omode)
                cands.append(dict(label='global_candidate(lam=%.4f)' % best['lam'], change=('context_and_law' if graph_label == 'G1' else 'law'), is_current=False, prop=newp, log2_B=l2(newp.B), log2_S=l2(newp.S), log2_H=Hc, log2_J=math.log2(dc) + Hc, family_volume=newp.work(self.arity_sum, self.Kq), index=1, d_hat=dc, cap_nonincreasing_checked=(not (newp.B > prop.B)), cap_nonincreasing_vs_tight=(not (newp.B > B_tight))))
            elif best is not None: att['quantization'] = dict(skipped='the segment selected lambda = 0: the replicated seed law in a more expensive representation is not a new law; the fallback is the original G0 seed with its own cheaper sampling work')
            else: att['quantization'] = dict(skipped=att.get('optimizer_failure'))
            # ---- (7) selection: actual law vs the BEST unchanged-law comparator; else witness-only vs the CONSUMED baseline
            actual = [c for c in cands if c['change'] != 'witness_only']; wonly = [c for c in cands if c['change'] == 'witness_only']
            win, promoted = (JO.select(actual, inc_best, p['promotion_margin']) if actual else (inc_best, False))
            if not promoted and wonly:
                w2, pr2 = JO.select(wonly, inc_consumed, p['promotion_margin'])
                if pr2: win, promoted, witness_only = w2, True, True
            att.update(candidates=[{k: v for k, v in c.items() if k != 'prop'} for c in cands], winner=win['label'], promoted=promoted, witness_only=witness_only, comparator=('best_same_law' if not witness_only else 'consumed'), selection_rule='actual law: >= 1 % lower J than the best checked unchanged-law candidate (own tightest cap + common tightest seed S witness; S / H / d / J rebuilt together); witness-only: >= 1 % lower J than the consumed baseline')
            if promoted:
                clk.poll('before the epoch commit'); newp = win['prop']
                if witness_only: owned_new = B_.charge(newp.bytes, 'global epoch %d law (same tables, tighter cap)' % len(self.epochs)); moved = 0           # mirrors DGP5: the shared tables are charged anew; the old epoch's release balances the account
                else: owned_new = cand_bytes; moved = cand_bytes; cand_bytes = 0                                                                            # the quantization charge becomes the epoch's owned storage
                self.joint_bytes += owned_new; self.retained_bytes += owned_new
                try: ep = self._commit_epoch(newp, 'promoted:%s' % win['label'], end, B_)
                except BaseException:
                    self.joint_bytes -= owned_new; self.retained_bytes -= owned_new
                    if witness_only: B_.release(owned_new)
                    else: cand_bytes = moved
                    raise
                att['committed_epoch'] = ep.index; self.promotion = dict(epoch=ep.index, label=win['label'], witness_only=witness_only, graph=graph_label, log2_J_before_consumed=inc_consumed['log2_J'], log2_J_before_best_same_law=inc_best['log2_J'], log2_J_after=win['log2_J']); self.activation_pending = not witness_only; self.mech['promotion'] = self.promotion
                if not witness_only: self.graph = dict(label=graph_label, parents={int(v): list(parents[v]) for v in parents}, plan_cap=PB.sha256, plan_moment=PS.sha256)
            T_after = work_end - tnow(); J_committed = win['log2_J'] if promoted else inc_consumed['log2_J']; passed, pb = JO.payback(J_committed, inc_consumed['log2_J'], T_before, T_after); att['payback'] = dict(passed=passed, **pb, J_committed_log2=J_committed, J_incumbent_log2=inc_consumed['log2_J'], construction_seconds=tnow() - t0, note='heuristic forecast ratio; never a certification')
            att['status'] = 'PROMOTED' if promoted else 'KEPT_INCUMBENT'
            if not promoted: att['label'] = 'no checked candidate promoted under the tested graph / circuit / objective / budget'
        except JP.RefusedJoint as e: att.update(status='REFUSED', kind=e.kind, why=str(e.reason)[:240], label='no checked candidate promoted under the tested graph / circuit / objective / budget')
        except CE.Refused as e: att.update(status='REFUSED', kind=e.kind, why=str(e.reason)[:240], label='no checked candidate promoted under the tested graph / circuit / objective / budget')
        except StreamRefused as e: att.update(status='REFUSED', kind=e.kind, why=str(e.reason)[:240], label='no checked candidate promoted under the tested graph / circuit / objective / budget')
        except (Deadline, IG.Deadline) as e: att.update(status='REFUSED', kind='DEADLINE', why=str(e)[:240], label='no checked candidate promoted under the tested graph / circuit / objective / budget')
        except CE.Defect as e: att.update(status='DEFECT', why=str(e)[:240]); self.mech['candidate_defect'] = str(e)[:200]
        except (ValueError, OverflowError, ZeroDivisionError, FloatingPointError) as e: att.update(status='NUMERIC', why=repr(e)[:240])
        except AssertionError as e: att.update(status='DEFECT', why=str(e)[:240]); self.mech['candidate_defect'] = str(e)[:200]
        finally:
            if cand_bytes: B_.release(cand_bytes)
            if g1_bytes: B_.release(g1_bytes)                                                                        # the replicated seed on the graph is never retained (a promoted candidate owns fresh conditionals)
            if workspace: B_.release(workspace)
            self.candidate = None
        self.refinement_ended = self.refinement_ended or ('attempt cap (one global attempt per request)' if att.get('status') in ('PROMOTED', 'KEPT_INCUMBENT') else 'attempt ended: %s' % att.get('status'))
        att['seconds'] = tnow() - t0; att['ended_offset_s'] = tnow() - self.allowance_start; att['workspace_released_bytes'] = workspace; self.attempts.append(att); self.mech['attempts'] = self.attempts; self.mech['refinement_ended'] = self.refinement_ended
        self.measurements.append(dict(kind='joint_action', action='global_optimize', seconds=att['seconds'], completed=(att.get('status') in ('PROMOTED', 'KEPT_INCUMBENT')), features=dict(status=att.get('status'), promoted=att.get('promoted'), graph=(att.get('graph') or {}).get('label'))))
        return att
    # ---- bounded activation of a promoted law (charged to sampling work; recorded separately from construction)
    def activation_action(self, hard):
        p = self.profile; t0 = tnow(); d0 = self.draws; nb = 0; r = None; checks = 0
        if not self.can_activate(): return dict(status='NOT_APPLICABLE')
        while nb < p['activation_batches'] and self.stage == 'READY':
            if tnow() >= hard: break
            r = self.batch(hard, hard, B_override=p['activation_batch']); nb += (r == 'COMMITTED')
            if r != 'COMMITTED': break
            if self.stage == 'READY': self.check(); checks += 1
        self.activation_pending = False; self.activation = dict(status=('COMPLETE' if nb == p['activation_batches'] else 'SHORT' if self.stage == 'READY' else 'CLOSED'), batches=nb, draws=self.draws - d0, checks=checks, seconds=tnow() - t0, epoch=(self.epoch.index if self.epoch else None), last=r, cap_draws=p['activation_batches'] * p['activation_batch'], forecast_metadata_reset='none required: the planner forecast uses cumulative width / time statistics (no unchanged-epoch assumption)', note='bounded activation of the promoted law: certificate / risk unchanged; charged to sampling work')
        self.mech['activation'] = self.activation; self.measurements.append(dict(kind='joint_action', action='global_activation', seconds=self.activation['seconds'], completed=(nb == p['activation_batches']), features=dict(batches=nb, draws=self.draws - d0))); return self.activation
    def diagnostics(self):
        d = super().diagnostics(); d['joint'].update(kind='global', global_mode=self.mode, objective=self.objective_mode(), graph=self.graph, promotion=self.promotion, activation=self.activation); d['global'] = d['joint']; return d
