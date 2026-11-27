"""DGP5 joint conditional construction, part 4: the statistical stream (brief sections 4-9). JointStream = ONE accepted IG.Certificate (unchanged class) over the fine inventory + immutable proposal EPOCHS (joint_proposal.Proposal)
on the parent canonical model M_par (identity or the already available exact-quotient parent with its checked response maps); weights X = W_int(x) / (C_int q_t(x)) with W_int = scale_F W_0 (BR.integerize of the parent
model WITHOUT its scalar; the scalar is restored exactly once by scale_to_original), C_int = scale_F B_t (1 + rho_cap) in W_int units; responses = exact indicators (identity) or the exact decoder values (exact parent).
Stages (atomic; the ONE absolute optional allowance end is fixed at the first entry and never reopened): INIT -> ORDER (guarded elimination order) -> SEED (joint_proposal.compile_seed; must finish by 50 % of the
allowance) -> FINE (fine float / log tables + response matrices; admitted) -> NUMERIC (joint_widening; the Certificate with THIS stream's risk; fingerprint admitted / polled BEFORE the final readiness poll) -> READY.
Explicit CHARGED actions after READY (the planner calls them inside the exploration account): pilot(...) = 1,024 committed draws in batches of 256 pinned to the seed epoch (committed ONCE to the certificate; odd draw
ids -> the fit half: Z_proxy = mean W_0 / q_seed in log2 form, HEURISTIC; even ids -> held out, never consulted for fitting / ranking / payback; must finish by 65 % of the allowance, else the checked seed is kept and
optimization skipped); refine(...) = ONE bounded update attempt (<= 2 in total; the second only after payback): family selection (joint_optimize), both coefficient passes (joint_witness), the frontier of actual quantized
laws each with its OWN fresh cap / moment witnesses, the explicit unchanged-law candidate (S_ref on both sides; the consumed cap as baseline) and the same-law tighter-cap candidate, promotion at >= 1 % lower J =
d_hat x H, the epoch switch (no pending batch; cert.eps_num = max over consumed epochs INCLUDING the candidate before its first batch; the normalizer diagnostic reset per epoch; the old epoch's storage released after
its references are dropped), payback J_committed / J_incumbent < T_after / T_before. Modes: 'seed' (no refine), 'joint', 'cap_only' (normalized b rows; J = d_hat x B), 'moment_only' (normalized sqrt a rows with their
own checked cap; J = d_hat x S). Every refused candidate releases only candidate ownership; the incumbent RNG, law, certificate, pending batch and risk ledger are untouched. Numerical proof: joint_widening maps every
float operation of the batch (fine log lookups, log2 of exact <= 2^40 counts, the two constant logs, the final combination) to its error term; the integer CDF draw is exact (law = trunc = 0 under the RNG assumption)."""
import sys, os, math, json, hashlib
from fractions import Fraction as F
import numpy as np
from pgm.algorithms.quotient import pac_actions as PA
from pgm.algorithms.quotient.pac_actions import Stream, StreamRefused, canon_to_model, tnow, Deadline, inf, log2
from pgm.algorithms.block import integrated as IG, blockres as BR; from pgm.algorithms.quotient import coarse_envelope as CE
from pgm.algorithms.quotient import joint_proposal as JP, joint_witness as JW, joint_optimize as JO, check_joint as CJ
from pgm.algorithms.quotient.residual_max_envelope import ZERO, norm_up, from_fraction_up, to_fraction, mul_exact, log2_up

MODES = ('seed', 'joint', 'cap_only', 'moment_only')


def joint_widening(fine_fts, n, scale_F_bits, E_mag, resp_rel):
    """numerical widening of the joint stream, operation by operation (the accepted numerical_widening's conventions): (c') the fine-factor weight (nf log2 lookups within 1 ulp of |log2| <= R_b, nf - 1 partial sums);
    (q) the law: n log2(count) terms (counts <= 2^40 are EXACT in binary64; |log2 c| <= 40), n partial sums; (k) two constant logs (log2 scale_F of an integer of scale_F_bits bits; log2 m_B of a 128-bit mantissa) and
    their sum; (e') six additions / subtractions in the final combination on magnitudes <= mags, the exact integer exponent E = E_fine - e_B + 40 n entering once (5 u |E|). The integer-CDF draw is exact: law = trunc = 0.
    The analyzed cap is EXACT (W_0 <= B q by the checker), so rho_cap = rho_X (the implemented weight's relative error) and the consumed cap is B (1 + rho_cap)."""
    u = IG.UF; L2 = F(145, 100)
    def logerr(mag): return u * (F(mag) + 1)
    SRf = sum(b.R for b in fine_fts); nf = len(fine_fts); d_zf = sum(logerr(b.R) for b in fine_fts) + u * nf * (SRf + nf)
    d_q = n * logerr(JP.D_BITS) + u * n * (n * JP.D_BITS + n)
    mag_sF = int(scale_F_bits) + 1; mag_B = 128; d_k = logerr(mag_sF) + logerr(mag_B) + u * 2 * (mag_sF + mag_B + 4)
    mags = SRf + nf + n * JP.D_BITS + n + mag_sF + mag_B + int(E_mag); d_fin = 6 * u * mags + 5 * u * int(E_mag)
    d_total = d_zf + d_q + d_k + d_fin; rho_X_log = L2 * d_total * (1 + d_total); rho_fine = IG.comb(*[b.rho for b in fine_fts]) if fine_fts else F(0); rho_X = (1 + rho_X_log) * (1 + rho_fine) - 1
    rho_f = resp_rel + 4 * u; law = F(0); trunc = F(0)
    return dict(rho_X=rho_X, rho_cap=rho_X, rho_f=rho_f, law=law, trunc=trunc, eps_num=2 * rho_X + rho_f + law + trunc, delta_log_total=d_total, max_log_mag=mags, parts=dict(d_zf=d_zf, d_q=d_q, d_k=d_k, d_fin=d_fin, rho_fine=rho_fine))


class Epoch:
    """an immutable committed proposal epoch: the law, its consumed cap (compact + the float pieces of the batch constant), its numerical allowance, the certificate t at commit, draw range, fingerprint"""
    __slots__ = ('index', 'prop', 'B_eff_log2', 'logB_m', 'e_B', 'eps_num', 'rho_X', 'cap_tol', 'E_int', 't_commit', 'draws_from', 'draws_to', 'fingerprint', 'record', 'zcert', 'parent', 'committed_at', 'allowance_end', 'draws_n', 'sumX', 'sumX2', 'maxX', 'zero_n')


class JointStream(Stream):
    def __init__(self, sid, M_fine, M_par, par_stages, seed, eps, delta_s, opts, label=None, scale_to_original=None, mode='joint', profile=None):
        assert mode in MODES, mode; model = canon_to_model(M_par); queries = [(v, a) for v in range(len(M_fine.cards)) for a in range(M_fine.cards[v])]
        super().__init__(sid, 'joint', model, queries, seed, eps, delta_s, opts, label=label or 'joint(%s)' % mode, scale_to_original=(M_par.scalar if scale_to_original is None else scale_to_original))
        self.M_fine = M_fine; self.M_par = M_par; self.par_stages = par_stages; self.n_par = len(M_par.cards); self.mode = mode; self.profile = dict(profile or JP.PROFILE_PRODUCTION); self.mech.update(joint_mode=mode, profile=self.profile, parent_exact_stages=len(par_stages), parent_cards=list(M_par.cards))
        self.epochs = []; self.epoch = None; self.joint_bytes = 0; self.allowance_end = None; self.allowance_start = None; self.phase_ends = None; self.attempts = []; self.refinement_ended = None; self.pilot = None; self.pairs = None; self.updated_vars = set()
        self.fit = dict(n=0, lmax=-inf, lsum=0.0); self.held = dict(n=0, lmax=-inf, lsum=0.0); self.pilot_store = None; self.pairs_bytes = 0; self.bound_kind = 'target_over_direct_conditional_law'; self.mech['bound_kind'] = self.bound_kind; self.epoch_switches = 0; self.batch_pins = []
    # ---- ownership (DGP5 finding 3)
    OWNED_ATTRS = ('fine_bytes', 'joint_bytes')
    def _drop_owned(self):
        """DGP6 repair (finding 2): seed_prop, the interaction-score dict and every candidate reference are dropped as well (the DGP5 close retained the 992 B seed law and the score dict after release); idempotent"""
        dropped = []
        for attr in ('fine', 'fLM', 'fstr', 'fscope'):
            if getattr(self, attr, None): setattr(self, attr, []); dropped.append(attr)
        for ep in self.epochs:
            if ep.prop is not None: ep.prop = None; dropped.append('epoch_%d_law' % ep.index)
        for attr in ('pilot_store', 'seed_prop', 'pairs', 'candidate', 'graph'):
            if getattr(self, attr, None) is not None: setattr(self, attr, None); dropped.append(attr)
        self.epoch = None; return dropped
    def stage_features(self, st): return dict(n=self.n_par, entries=sum(len(x['values']) for x in self.model['factors']), K=self.K, kind='joint', mode=self.mode)
    # ---- the allowance (ONE absolute end; phase ends derived once)
    def _set_allowance(self, until):
        if self.allowance_end is None:
            A = max(0.0, until - tnow()); self.allowance_start = tnow(); self.allowance_end = until; p = self.profile
            self.phase_ends = dict(seed=self.allowance_start + p['seed_frac'] * A, pilot=self.allowance_start + p['pilot_frac'] * A, reserve=self.allowance_end - p['reserve_frac'] * A, end=self.allowance_end)
            self.mech['allowance'] = dict(absolute_end=self.allowance_end, start=self.allowance_start, total_s=A, phase_ends_offset_s={k: v - self.allowance_start for k, v in self.phase_ends.items()}, rule='ONE stored absolute end; pauses / yields never extend it; final 10 % reserved; seed by 50 %, pilot by 65 %')
    def allowance_left(self): return (self.allowance_end - tnow()) if self.allowance_end is not None else None
    # ---- preparation
    def prepare(self, deadline, cdead=None, until=None):
        until = deadline if until is None else min(until, deadline); self._set_allowance(until); eff = min(deadline, self.allowance_end); t0 = tnow()
        try:
            while self.stage not in ('READY', 'COMPLETE', 'CLOSED'):
                if tnow() >= self.allowance_end:
                    self.measurements.append(dict(kind='joint_stage', stage=self.stage, seconds=0.0, completed=False, censored='ALLOWANCE', features=self.stage_features(self.stage))); return self._close('ALLOWANCE in joint stage %s: the optional preparation allowance (absolute end) expired before READY (not reopened)' % self.stage)
                if tnow() >= until: return 'YIELD'
                t0 = tnow(); st = self.stage
                if st == 'INIT': self._j_order(eff)
                elif st == 'INTEGERIZED': self._j_seed(min(eff, self.phase_ends['seed']))
                elif st == 'CONTRACTED': self._j_fine_tables(min(eff, self.phase_ends['reserve']))
                elif st == 'CONSTANTS': self._j_numeric(eff)
                dt = tnow() - t0; self.t_prep += dt; self.measurements.append(dict(kind='joint_stage', stage=st, seconds=dt, completed=True, features=self.stage_features(st)))
            return self.stage
        except Deadline as e: self.measurements.append(dict(kind='joint_stage', stage=self.stage, seconds=tnow() - t0, completed=False, censored='DEADLINE', features=self.stage_features(self.stage))); return self._close('DEADLINE in joint stage %s (%s)' % (self.stage, e))
        except (IG.RangeRefused, CE.Refused) as e: self.measurements.append(dict(kind='joint_stage', stage=self.stage, seconds=tnow() - t0, completed=False, censored=getattr(e, 'kind', 'RANGE'), features=self.stage_features(self.stage))); return self._close('%s in joint stage %s: %s' % (getattr(e, 'kind', 'RANGE'), self.stage, str(getattr(e, 'reason', e))[:160]))
        except (JP.RefusedJoint, StreamRefused) as e: self.measurements.append(dict(kind='joint_stage', stage=self.stage, seconds=tnow() - t0, completed=False, censored=e.kind, features=self.stage_features(self.stage))); return self._close('%s in joint stage %s: %s' % (e.kind, self.stage, str(e.reason)[:160]))
        except CE.Defect as e: self.measurements.append(dict(kind='joint_stage', stage=self.stage, seconds=tnow() - t0, completed=False, censored='DEFECT', features=self.stage_features(self.stage))); self.defect = 'joint construction defect (optional route closed, nothing published from it): %s' % str(e)[:160]; self.mech['construction_defect'] = self.defect; return self._close('DEFECT in joint stage %s: %s' % (self.stage, str(e)[:160]))
        except (ValueError, OverflowError, ZeroDivisionError) as e: self.measurements.append(dict(kind='joint_stage', stage=self.stage, seconds=tnow() - t0, completed=False, censored='NUMERIC', features=self.stage_features(self.stage))); return self._close('NUMERIC in joint stage %s: %s' % (self.stage, repr(e)[:160]))
        except Exception as e:                                                                              # DGP5 validity amendment 1: an UNEXPECTED exception inside the OPTIONAL joint stream closes THIS stream typed (recorded with its traceback) and never the request
            import traceback; self.measurements.append(dict(kind='joint_stage', stage=self.stage, seconds=tnow() - t0, completed=False, censored='INTERNAL', features=self.stage_features(self.stage))); self.mech['internal_error'] = dict(stage=self.stage, error=repr(e)[:200], traceback=traceback.format_exc()[-1500:]); self.defect = 'joint internal error (optional route closed, nothing published from it): %s' % repr(e)[:120]; self.mech['construction_defect'] = self.defect; return self._close('INTERNAL in joint stage %s: %s' % (self.stage, repr(e)[:160]))
    def _j_order(self, deadline):
        clk = CE.Clock(deadline, {}); B_ = self.opts.get('budget_obj') or CE.Budget(CE.CONSTRUCTOR_BYTES); self.order, vols = CE.elimination_order(list(self.M_par.cards), [tuple(sc) for sc, _ in self.M_par.factors], clk, B_); self.mech['elimination'] = dict(order=self.order, max_bucket_volume=max(vols) if vols else 0); self.stage = 'INTEGERIZED'
    def _j_seed(self, deadline):
        """the checked seed (brief section 5); its conditionals are owned by the stream (joint_bytes); a zero U = the zero-target terminal"""
        B_ = self.opts.get('budget_obj') or CE.Budget(CE.CONSTRUCTOR_BYTES); clk = CE.Clock(deadline, {}); t0 = tnow(); trace = []
        prop, rec, owned = JP.compile_seed(self.M_par, self.order, self.profile, B_, clk, deadline_fn=(lambda: tnow() >= deadline), trace=trace)
        if owned > self.profile['owned_cap_bytes']: B_.release(owned); raise StreamRefused('MEMORY_POLICY', 'the seed owns %d B > the 64 MiB joint storage cap' % owned)
        self.joint_bytes += owned; self.retained_bytes += owned; self.ph['seed'] = tnow() - t0; self.mech['seed'] = {k: v for k, v in rec.items() if k != 'plan'}; self.mech['seed']['plan_groups'] = len(rec['plan']); self.seed_prop = prop
        if rec['zero_U']: self.Z = F(0); self.witness = False; self.stage = 'COMPLETE'; self.mech['terminal'] = 'ZERO_MASS_PROVED_BY_UPPER_MODEL'; return      # a checked zero U proves zero target mass (never READY with B = 0)
        self.stage = 'CONTRACTED'
    def _j_fine_tables(self, deadline):
        fns_F, const_F, scale_F, mult_F, factorless_F = BR.integerize(self.model)
        if const_F == 0: self.Z = F(0); self.witness = False; self.stage = 'COMPLETE'; self.mech['terminal'] = 'ZERO_EVIDENCE'; return
        self.scale_F = scale_F; B_ = self.opts.get('budget_obj'); self.fine = []
        for i, f in enumerate(fns_F):
            if (i & 15) == 15 and tnow() >= deadline: raise Deadline('joint fine tables (factor %d)' % i)
            if B_ is not None: self.fine_bytes = getattr(self, 'fine_bytes', 0) + B_.charge(np.asarray(f.arr).size * 16 + 128, 'joint fine float + log table (factor %d)' % i)
            self.fine.append(IG.ft_from_int(f, self.cards))
        self.E_fine = sum(b.e for b in self.fine); self.fLM = []; self.fstr = []; self.fscope = []
        for i, b in enumerate(self.fine):
            if (i & 15) == 15 and tnow() >= deadline: raise Deadline('joint fine log tables (factor %d)' % i)
            with np.errstate(divide='ignore'): self.fLM.append(np.where(b.M > 0, np.log2(np.maximum(b.M, 1e-300)), -inf).reshape(-1))
            strides = {}; s_ = 1
            for u in reversed(b.scope): strides[u] = s_; s_ *= self.cards[u]
            self.fstr.append(strides); self.fscope.append(b.scope)
        self.Dm = []; self.col0 = []; col = 0; resp_rel = F(0)
        for v in range(self.n_par):
            card_f = self.M_fine.cards[v]; Dm = np.zeros((self.M_par.cards[v], card_f))
            if not self.par_stages: Dm[np.arange(card_f), np.arange(card_f)] = 1.0
            else:
                for a in range(card_f):
                    c, d = CE.compose_decoder(self.par_stages, v, a); Dm[c, a] = float(d); resp_rel = 2 * IG.UF
            self.Dm.append(Dm); self.col0.append(col); col += card_f
        self.Kq = col; self.resp_rel = resp_rel; self.sq = list(self.queries); self.qmap = {q: self.qix[q] for q in self.sq}; self.alpha = float(self.delta_s) / self.Kq; self.arity_sum = sum(2 for _ in range(self.n_par)) + sum(len(sc) + 1 for sc, _ in self.M_par.factors)
        self.retained_bytes += sum(b.M.nbytes for b in self.fine) + sum(d.nbytes for d in self.Dm)
        if tnow() >= deadline: raise Deadline('joint fine tables (before NUMERIC)')
        self.stage = 'CONSTANTS'
    def _epoch_constants(self, prop):
        """the batch constants + numerical proof of ONE epoch's law (its cap B in W_0 units)"""
        e_B, m_B = prop.B
        if m_B == 0: raise StreamRefused('SUPPORT', 'an epoch cap of zero (zero target mass should have terminated)')
        E_int = self.E_fine - e_B + JP.D_BITS * self.n_par
        if abs(E_int) >= 1 << 50: raise StreamRefused('NUMERIC_RANGE', 'exponent sum too large for an exact float')
        wid = joint_widening(self.fine, self.n_par, self.scale_F.bit_length(), abs(E_int), self.resp_rel)
        if wid['delta_log_total'] > F(1, 4): raise StreamRefused('NUMERIC_RANGE', 'log-domain error budget %s too large' % float(wid['delta_log_total']))
        eps_num = IG.fup(wid['eps_num']); rho_X = IG.fup(wid['rho_X']); rho_cap = IG.fup(wid['rho_cap']); cap_margin = IG.up(IG.up(log2(1.0 + rho_cap)) + 2 ** -40); cap_tol = IG.up(log2(1.0 + 2 * rho_X)) + 2 ** -40
        logB_m = math.log2(m_B); log_sF = float(IG.lg(F(self.scale_F))); B_eff_log2 = e_B + logB_m + cap_margin
        return dict(e_B=e_B, logB_m=logB_m, log_sF=log_sF, E_int=E_int, eps_num=eps_num, rho_X=rho_X, rho_cap=rho_cap, cap_margin=cap_margin, cap_tol=cap_tol, B_eff_log2=B_eff_log2, widening={k: (float(v) if isinstance(v, F) else v) for k, v in wid.items() if k != 'parts'}, widening_parts={k: float(v) for k, v in wid['parts'].items()},
                    cap_units=dict(cap_W0_log2=B_eff_log2, cap_Wint_log2=B_eff_log2 + log_sF, unit='W_int = scale_F x W_0 (parent canonical target without its scalar); X = W_int(x) / (2^cap_Wint_log2 q(x)); the checked cap B is in W_0 units, consumed as B (1 + rho_cap)', checked_log2_B_W0=prop.log2_B()))
    def _commit_epoch(self, prop, reason, deadline, budget):
        """commit a new epoch BEFORE its first draw: constants, eps_num = max over consumed epochs incl. this one, a fresh normalizer diagnostic, the fingerprint (admitted / polled); the previous epoch's law storage is released
        after its references are dropped (its record stays)"""
        if self.pending is not None: raise StreamRefused('PENDING', 'an epoch switch with a pending batch is refused')
        # DGP6 repair (finding 4: transactional epoch commit): EVERY variable-size preparation / diagnostic first (constants, fingerprint, the prior epoch's normalizer diagnostic + record), then the FINAL allowance poll, then the bounded swap
        k = self._epoch_constants(prop); ep = Epoch(); ep.index = len(self.epochs); prior_records = [e.record for e in self.epochs]                  # DGP7 repair R5: the variable-sized epochs record list is assembled BEFORE the authoritative poll
        ep.index = len(self.epochs); ep.prop = prop; ep.B_eff_log2 = k['B_eff_log2']; ep.logB_m = k['logB_m']; ep.e_B = k['e_B']; ep.eps_num = k['eps_num']; ep.rho_X = k['rho_X']; ep.cap_tol = k['cap_tol']; ep.E_int = k['E_int']; ep.t_commit = (self.cert.t if hasattr(self, 'cert') else 0); ep.draws_from = self.draws; ep.draws_to = None; ep.parent = (self.epochs[-1].index if self.epochs else None); ep.allowance_end = self.allowance_end; ep.draws_n = 0; ep.sumX = 0.0; ep.sumX2 = 0.0; ep.maxX = 0.0; ep.zero_n = 0
        ep.zcert = IG.ZCertificate(float(self.delta_s)); ep.fingerprint = self._fingerprint_of(ep, deadline, budget)
        eps_after = max(self.cert.eps_num, ep.eps_num) if hasattr(self, 'cert') else ep.eps_num
        ep.record = dict(index=ep.index, reason=reason, proposal=prop.record(), constants={kk: vv for kk, vv in k.items() if kk not in ('widening_parts',)}, widening_parts=k['widening_parts'], eps_num_epoch=ep.eps_num, eps_num_certificate_after=eps_after, cert_t_at_commit=ep.t_commit, draws_from=ep.draws_from, predecessor=ep.parent, fingerprint=ep.fingerprint, committed_offset_s=(tnow() - self.allowance_start) if self.allowance_start else None, absolute_allowance_end=self.allowance_end, live_joint_bytes=self.joint_bytes)
        prev = self.epoch; prev_diag = None
        if prev is not None: prev_diag = dict(interval=prev.zcert.interval(), cap_log2_W0=prev.B_eff_log2, draws=self.draws - prev.draws_from, epoch_X_mean=((prev.sumX / prev.draws_n) if getattr(prev, 'draws_n', 0) else None), epoch_ESS_DIAGNOSTIC=((prev.sumX ** 2 / prev.sumX2) if getattr(prev, 'sumX2', 0.0) > 0 else None), epoch_max_X=getattr(prev, 'maxX', None), note='fixed-cap EPOCH-LOCAL diagnostic; never pooled across epochs')
        t_commit = tnow()                                                                                        # DGP9 repair (original DGP7 finding F3): ONE authoritative sample decides AND stamps the commit (the DGP8 code tested one sample and stamped a second)
        if deadline is not None and t_commit >= deadline: raise Deadline('epoch commit: the allowance passed during the preparation / diagnostics (nothing committed)')
        # ---- swap (bounded references and counters only)
        ep.committed_at = t_commit; ep.record['committed_offset_s'] = (t_commit - self.allowance_start) if self.allowance_start else None; self.log_sF = k['log_sF']
        if hasattr(self, 'cert'): self.cert.eps_num = eps_after                                                   # re-widens every historical term under the accepted interpretation (included BEFORE the first batch of the new epoch)
        else: self.cert = IG.Certificate(self.Kq, self.alpha, ep.eps_num, float(self.eps), self.opts['schedule']); self.mech['alpha_per_coordinate'] = self.alpha
        self.eps_num = self.cert.eps_num
        if prev is not None:
            prev.draws_to = self.draws; prev.record['draws_to'] = self.draws; prev.record['Z_over_cap_EB_DIAGNOSTIC_epoch'] = prev_diag
            if prev.prop is not None and prev.prop is not prop: n = prev.prop.bytes; prev.prop = None; self._release_joint(n, budget); prev.record['storage_released_bytes'] = n
        self.epochs.append(ep); self.epoch = ep; self.fingerprint = ep.fingerprint; self.epoch_switches += int(prev is not None); prior_records.append(ep.record); self.mech['epochs'] = prior_records; return ep
    def _release_joint(self, n, budget):
        if budget is not None and n: budget.release(min(n, self.joint_bytes)); self.joint_bytes -= min(n, self.joint_bytes); self.retained_bytes -= n
    def _fingerprint_of(self, ep, deadline, budget):
        """sha256 over every conditional's parents + counts (chunked, admitted, polled), the cap pieces, the risk, eps_num and the inventory"""
        h = hashlib.sha256(); h.update(repr((self.mode, ep.index, ep.prop.order, ep.B_eff_log2, ep.e_B, ep.logB_m, ep.eps_num, self.alpha, self.Kq, len(self.sq), self.scale_F)).encode())
        for v in ep.prop.order:
            c = ep.prop.conds[v]; h.update(repr((v, c.parents, c.counts.shape)).encode()); self._fp_table(h, c.counts, deadline, budget, 'conditional %d counts' % v)
        return h.hexdigest()
    def proposal_fingerprint(self, deadline=None, budget=None):
        return self._fingerprint_of(self.epoch, deadline, budget) if self.epoch is not None and self.epoch.prop is not None else (self.fingerprint if hasattr(self, 'fingerprint') else None)
    def _j_numeric(self, deadline):
        o = self.opts; cert_per_draw = self.Kq * 8 * 7 + 8 * self.n_par * 3; batch_used = o['batch']
        while batch_used > 1 and batch_used * cert_per_draw > IG.BATCH_BUDGET: batch_used //= 2
        self.batch_used = batch_used; self.cert_per_draw = cert_per_draw; B_ = o.get('budget_obj')
        self._commit_epoch(self.seed_prop, 'seed', deadline, B_); self.seed_prop = None
        self.mech.update(eps_num=self.eps_num, rho_X=self.epoch.rho_X, batch_used=batch_used, cap_units=self.epoch.record['constants']['cap_units'], cap_log2_total=self.epoch.record['constants']['cap_units']['cap_Wint_log2'], widening=self.epoch.record['constants']['widening'], widening_parts=self.epoch.record['widening_parts'], Kq=self.Kq)
        self.retained_bytes += batch_used * cert_per_draw
        if tnow() >= deadline: raise Deadline('joint numeric stage (before READY)')                     # the final readiness poll AFTER the fingerprint (DGP5 finding 4)
        self.stage = 'READY'
    # ---- batches
    def _flat_fine(self, z, i):
        idx = np.zeros(z.shape[0], dtype=np.int64)
        for u in self.fscope[i]: idx += z[:, u] * self.fstr[i][u]
        return idx
    def batch(self, deadline, hard=None, B_override=None, pilot=False):
        """one committed batch under the CURRENT epoch (pinned before generation); atomic: a hard cut abandons it and closes the stream"""
        if self.stage != 'READY': return self.stage
        hard = deadline if hard is None else hard; t0 = tnow(); ep = self.epoch; Bn = int(B_override or self.batch_used)
        try:
            X_states, logc = ep.prop.sample(self.rng, Bn); logz = np.zeros(Bn)
            if getattr(self, 'mutant_surrogate', False): logz = logc - JP.D_BITS * self.n_par + ep.B_eff_log2 + self.log_sF - self.E_fine      # CONTROLS ONLY: the weight of the CAP SURROGATE B q instead of W (every X = 1)
            else:
                for i in range(len(self.fine)): logz += self.fLM[i][self._flat_fine(X_states, i)]
            if tnow() >= hard: raise Deadline('joint batch at the hard work cutoff')
            zero = ~np.isfinite(logz); logW0q = np.where(zero, -2000.0, (logz - logc) + float(self.E_fine + JP.D_BITS * self.n_par) - self.log_sF)      # log2 (W_0 / q) in W_0 units (the fit statistic)
            logX = np.where(zero, -2000.0, logW0q - ep.B_eff_log2); mx = float(logX[~zero].max()) if (~zero).any() else -inf
            assert mx <= ep.cap_tol, 'joint importance weight exceeds the certified cap beyond its proved error bound (certificate defect): log2 X = %r > %r' % (mx, ep.cap_tol)
            X = np.where(zero, 0.0, np.minimum(1.0, np.exp2(logX))); f = np.zeros((Bn, self.Kq))
            for v in range(self.n_par): f[:, self.col0[v]:self.col0[v] + self.M_fine.cards[v]] = self.Dm[v][X_states[:, v]]
            ids = np.arange(self.draws, self.draws + Bn)
            # DGP6 repair (finding 4: transactional batch): every variable-size statistic is built in admitted SCRATCH (a copy of the small certificate state, the epoch's normalizer diagnostic, the fit / held-out accumulators),
            # the HARD clock is polled AFTER that work, and only then are the bounded references swapped; a crossing anywhere inside the assembly discards the batch and closes the stream (nothing committed)
            B_ = self.opts.get('budget_obj'); scratch = 0
            if B_ is not None: scratch = B_.charge(self.cert.K * 8 * 12 + 512 + Bn * 8, 'batch scratch (certificate copy)')
            try:
                import copy as _copy; cert2 = _copy.deepcopy(self.cert); zc2 = _copy.deepcopy(ep.zcert); fit2 = dict(self.fit); held2 = dict(self.held); store_add = None
                if pilot:
                    for half, mask in (('fit', (ids & 1) == 1), ('held', (ids & 1) == 0)):
                        acc = fit2 if half == 'fit' else held2; vals = logW0q[mask & ~zero]
                        if vals.size:
                            m = float(vals.max()); lm = max(acc['lmax'], m); acc['lsum'] = acc['lsum'] * (2.0 ** (acc['lmax'] - lm) if acc['n'] else 0.0) + float(np.exp2(vals - lm).sum()); acc['lmax'] = lm
                        acc['n'] += int(mask.sum())
                    if self.pilot_store is not None: store_add = (X_states.copy(), logW0q.copy(), ids.copy())
                cert2.update_batch(X, f); zc2.update_batch(X)
                # DGP9 repair (original DGP7 finding F3): EVERY variable-size reduction of the batch (the draw-weight sums / maxima / zero counts, the pin bounds, the positivity witness) is computed into scalars BEFORE the one
                # authoritative sample; after the sample only bounded scalar / reference swaps happen (the DGP8 code reduced X after its final poll)
                zero_n = int(zero.sum()); sX = float(X.sum()); sX2 = float((X * X).sum()); mX = float(X.max()); any_pos = bool((X > 0).any()); pin = (ep.index, int(ids[0]), int(ids[-1]))
                t_commit = tnow()
                if t_commit >= hard: raise Deadline('joint batch: the hard cutoff passed during the statistics assembly (nothing committed)')
                # ---- swap (bounded)
                self.cert = cert2; ep.zcert = zc2; self.fit = fit2; self.held = held2
                if store_add is not None: self.pilot_store['states'].append(store_add[0]); self.pilot_store['logW0q'].append(store_add[1]); self.pilot_store['ids'].append(store_add[2])
            finally:
                if scratch: B_.release(scratch)
            self.draws += Bn; self.zero_draws += zero_n; self.sumX += sX; self.sumX2 += sX2; self.maxX = max(self.maxX, mX); self.maxlogX = max(self.maxlogX, mx)
            ep.draws_n = getattr(ep, 'draws_n', 0) + Bn; ep.sumX = getattr(ep, 'sumX', 0.0) + sX; ep.sumX2 = getattr(ep, 'sumX2', 0.0) + sX2; ep.maxX = max(getattr(ep, 'maxX', 0.0), mX); ep.zero_n = getattr(ep, 'zero_n', 0) + zero_n      # DGP6 repair (finding 8): epoch-LOCAL weight statistics
            if any_pos: self.witness = True
            self.batches += 1; dt = t_commit - t0; self.t_sample += dt; self._pin(*pin); self._measure_batch(dt, Bn, ep.index, pilot); return 'COMMITTED'
        except (IG.Deadline, Deadline) as e: self.abandoned += 1; self.t_sample += tnow() - t0; return self._close('joint batch abandoned at a hard cut (%s); %d committed batches retained' % (e, self.batches))
        except IG.RangeRefused as e: self.abandoned += 1; self.stream_refusal = str(e); self.t_sample += tnow() - t0; return self._close('NUMERIC_RANGE_REFUSED in a joint batch: %s' % str(e)[:120])
        except AssertionError as e: self.abandoned += 1; self.defect = str(e)[:200]; self.mech['certificate_defect'] = self.defect; self.t_sample += tnow() - t0; return self._close('CERTIFICATE_DEFECT in a joint batch (rows withheld): %s' % str(e)[:120])
        except (CE.Refused, StreamRefused) as e: self.abandoned += 1; self.stream_refusal = str(e); self.t_sample += tnow() - t0; return self._close('%s in a joint batch (resource refusal; nothing committed): %s' % (getattr(e, 'kind', 'REFUSED'), str(getattr(e, 'reason', e))[:120]))      # DGP7 repair R4: a constructor refusal inside the batch closes THIS stream typed
    # ---- DGP8 repair (DGP7 review: retained-object accounting): per-batch records are BOUNDED -- the first BOUNDED_RECORDS batches keep full records, later batches fold into ONE aggregate record (seconds / draws summed, so every
    # cost sum over measurements is unchanged) and ONE overflow counter for the pins; the stream never retains an unbounded variable-size object outside its byte ledger
    BOUNDED_RECORDS = 64
    def _pin(self, e, a, b):
        if len(self.batch_pins) < self.BOUNDED_RECORDS: self.batch_pins.append((e, a, b))
        else: self.batch_pins_overflow = getattr(self, 'batch_pins_overflow', 0) + 1; self.batch_pins_last = (e, a, b)
    def _measure_batch(self, dt, Bn, epoch, pilot):
        agg = getattr(self, '_batch_agg', None)
        if agg is None:
            if sum(1 for m in self.measurements if m.get('kind') == 'joint_batch') < self.BOUNDED_RECORDS: self.measurements.append(dict(kind='joint_batch', seconds=dt, completed=True, features=dict(B=Bn, n=self.n_par, fine_factors=len(self.fine), Kq=self.Kq, epoch=epoch, pilot=pilot))); return
            agg = dict(kind='joint_batch', seconds=0.0, completed=True, aggregated=True, n_batches=0, draws=0, features=dict(n=self.n_par, Kq=self.Kq, note='per-batch records bounded at %d; later batches aggregated here (seconds / draws summed)' % self.BOUNDED_RECORDS)); self.measurements.append(agg); self._batch_agg = agg
        agg['seconds'] += dt; agg['n_batches'] += 1; agg['draws'] += Bn
    # ---- the explicit charged actions
    def pilot_action(self, hard):
        try: return self._pilot_action(hard)
        except (CE.Refused, StreamRefused) as e: self._close('%s in the joint pilot (resource refusal): %s' % (getattr(e, 'kind', 'REFUSED'), str(getattr(e, 'reason', e))[:120])); return dict(status='REFUSED', kind=getattr(e, 'kind', 'REFUSED'), why=str(getattr(e, 'reason', e))[:200])      # DGP7 repair R4
        except Exception as e:
            import traceback; self.mech['internal_error'] = dict(stage='pilot', error=repr(e)[:200], traceback=traceback.format_exc()[-1500:]); self.defect = 'joint internal error in the pilot (optional route closed): %s' % repr(e)[:120]; self.mech['construction_defect'] = self.defect; self._close('INTERNAL in the joint pilot: %s' % repr(e)[:160]); return dict(status='INTERNAL', error=repr(e)[:200])
    def _pilot_action(self, hard):
        """1,024 committed draws in batches of 256 pinned to the seed epoch, inside the pilot phase end; a short pilot keeps the checked seed and skips optimization; one certificate check afterwards"""
        if self.stage != 'READY' or self.pilot is not None: return dict(status='NOT_APPLICABLE')
        p = self.profile; end = min(hard, self.phase_ends['pilot']); t0 = tnow(); B_ = self.opts.get('budget_obj'); n_target = p['pilot_draws']; nb = 0; r = None
        store_bytes = (n_target * self.n_par * 8 + n_target * 16 + 1024)
        if B_ is not None: self.joint_bytes += B_.charge(store_bytes, 'joint pilot store'); self.retained_bytes += store_bytes
        self.pilot_store = dict(states=[], logW0q=[], ids=[], bytes=store_bytes); d0 = self.draws; tc0 = self.t_cert; ts0 = self.t_sample
        while self.draws - d0 < n_target and self.stage == 'READY':
            if tnow() >= end: break
            r = self.batch(end, hard, B_override=p['pilot_batch'], pilot=True); nb += (r == 'COMMITTED')
            if r != 'COMMITTED': break
            if nb == 1 and self.stage == 'READY': self.check()                                          # the same probe path as the lifted stream: a check after the FIRST and after the LAST committed batch (two checkpoints -> a forecast can exist)
        if self.stage == 'READY' and nb: self.check()
        drawn = self.draws - d0; short = drawn < n_target; d_seed = ((self.t_sample - ts0) + (self.t_cert - tc0)) / drawn if drawn else None
        zp = (self.fit['lmax'] + math.log2(self.fit['lsum']) - math.log2(self.fit['n'])) if (self.fit['n'] and self.fit['lsum'] > 0) else None
        zh = (self.held['lmax'] + math.log2(self.held['lsum']) - math.log2(self.held['n'])) if (self.held['n'] and self.held['lsum'] > 0) else None
        self.pilot = dict(status=('COMPLETE' if not short else ('SHORT' if self.stage == 'READY' else 'CLOSED')), batches=nb, draws=drawn, target=n_target, seconds=tnow() - t0, d_seed_s_per_draw=d_seed, log2_Z_proxy_fit=zp, log2_Z_proxy_heldout_DIAGNOSTIC=zh, fit_ids='odd draw ids', held_ids='even draw ids', fit_n=self.fit['n'], held_n=self.held['n'], epoch=self.epochs[0].index, last=r, ended_at_offset_s=(tnow() - self.allowance_start), note='Z_proxy is a HEURISTIC estimate (never a bound, never published); the held-out half never enters fitting / ranking / payback')
        if short: self.refinement_ended = 'short pilot (%d < %d draws): the checked seed is kept, optimization skipped' % (drawn, n_target)
        if zp is None and self.refinement_ended is None: self.refinement_ended = 'no positive Z_proxy from the fit half: the checked seed is kept, optimization skipped'
        self.mech['pilot'] = self.pilot; self.measurements.append(dict(kind='joint_action', action='pilot', seconds=tnow() - t0, completed=(not short), features=dict(draws=drawn, batches=nb))); return self.pilot
    def _d_hat(self, prop):
        w0 = self.epochs[0].prop.work(self.arity_sum, self.Kq) if self.epochs[0].prop is not None else self._work0; return self.pilot['d_seed_s_per_draw'] * prop.work(self.arity_sum, self.Kq) / w0
    def refine_action(self, hard, work_end):
        """ONE bounded update attempt (brief section 7); `work_end` = the request's work cutoff (T_before / T_after); returns the attempt record"""
        p = self.profile; t0 = tnow(); att = dict(index=len(self.attempts), started_offset_s=(tnow() - self.allowance_start) if self.allowance_start else None)
        if self.stage != 'READY': att.update(status='NOT_APPLICABLE', why='stream not READY'); self.attempts.append(att); return att
        if self.mode == 'seed': att.update(status='DISABLED', why='seed-only mode'); self.attempts.append(att); self.refinement_ended = 'seed-only mode'; return att
        if self.refinement_ended is not None: att.update(status='ENDED', why=self.refinement_ended); self.attempts.append(att); return att
        if len(self.attempts) >= p['max_attempts']: att.update(status='ENDED', why='attempt cap'); self.attempts.append(att); return att
        if self.pilot is None or self.pilot.get('log2_Z_proxy_fit') is None: att.update(status='SKIPPED', why='no pilot / no positive Z_proxy'); self.attempts.append(att); self.refinement_ended = att['why']; return att
        if len(self.attempts) >= 1 and not self.attempts[-1].get('payback', {}).get('passed'): att.update(status='ENDED', why='the first attempt did not pass payback'); self.attempts.append(att); self.refinement_ended = att['why']; return att
        end = min(hard, self.phase_ends['reserve'])
        if tnow() >= end: att.update(status='REFUSED', kind='ALLOWANCE', why='no optimization time left inside the original allowance'); self.attempts.append(att); self.refinement_ended = att['why']; return att
        B_ = self.opts.get('budget_obj') or CE.Budget(CE.CONSTRUCTOR_BYTES); clk = CE.Clock(end, {}); cards = list(self.M_par.cards); inc_ep = self.epoch; prop = inc_ep.prop; T_before = work_end - tnow(); att['T_before_s'] = T_before; self._work0 = self.epochs[0].prop.work(self.arity_sum, self.Kq) if self.epochs[0].prop is not None else getattr(self, '_work0', prop.work(self.arity_sum, self.Kq))
        pk = None; chg_pairs = 0
        try:
            if self.pairs is None: self.pairs, chg_pairs = JO.interaction_scores(self.M_par, B_, clk); self.joint_bytes += chg_pairs; self.retained_bytes += chg_pairs; self.pairs_bytes = chg_pairs
            exps = JO.rank_expansions(prop, self.pairs, cards, p['V_family'], exclude_vars=self.updated_vars); fam = exps[0] if exps else JO.choose_retune(prop, self.pairs, cards, exclude_vars=self.updated_vars)
            if fam is None: raise JP.RefusedJoint('NO_FAMILY', 'no admissible family (every variable already updated)')
            z = fam['z']; parents = tuple(fam['new_parents']); att.update(family=dict(z=z, parents=list(parents), expansion=(fam.get('add') is not None), added_variable=fam.get('add'), score=fam.get('score'), ratio=fam.get('ratio'), family_volume=JP.vol_of(parents, cards) * cards[z], candidates_ranked=[(e['z'], e['add'], round(e['ratio'], 4)) for e in exps[:5]]))
            deadline_fn = lambda: tnow() >= end; tp = tnow(); pk = JW.build_packet(self.M_par, prop, z, parents, self.order, p, B_, clk, deadline_fn); att['packet'] = dict(pk.record(), seconds=tnow() - tp, owned_bytes=pk.owned)
            if pk.owned > p['owned_cap_bytes'] - self.joint_bytes: raise JP.RefusedJoint('MEMORY_POLICY', 'the coefficient packet (%d B) exceeds the joint storage cap' % pk.owned)
            # the incumbent on the packet: B_tight = min(B_current, max b / theta_current); S_ref = min(S_current, sum a / theta_current, B_tight^2) -- used on BOTH sides; the CONSUMED cap stays the baseline
            inc = JW.witnesses_of(pk, pk.cond_ctx, S_ref=None); B_tight = min(prop.B, inc['B']); S_ref = min([s for s in (prop.S, inc['S']) if s[1]] + [norm_up(*mul_exact(B_tight, B_tight))])
            log2_eta = math.log2(float(self.eps)) + self.pilot['log2_Z_proxy_fit'] - math.log2(6.0); l2 = lambda x: (log2_up(x) if x[1] else -inf)
            inc_H = JO.H_log2(l2(S_ref), l2(prop.B), log2_eta, self.mode); d0 = self._d_hat(prop); incumbent = dict(label='current_epoch', is_current=True, log2_B=l2(prop.B), log2_S=l2(S_ref), log2_H=inc_H, log2_J=math.log2(d0) + inc_H, family_volume=prop.conds[z].family_volume(), index=-1, d_hat=d0)
            cands = []; laws = JO.frontier_laws(pk, prop, cards, p, self.mode, prop.B); rejected = [lab for lab, c, _ in laws if c is None]
            if B_tight < prop.B:                                                                           # the same-law tighter-cap candidate (a REAL candidate: it changes the normalized weights)
                newp = JP.Proposal(cards, prop.conds, prop.order, B_tight, S_ref, dict(kind='same_law_tighter_cap', packet=pk.sha256), predecessor=inc_ep.index); H = JO.H_log2(l2(S_ref), l2(B_tight), log2_eta, self.mode)
                cands.append(dict(label='same_law_tighter_cap', is_current=False, prop=newp, log2_B=l2(B_tight), log2_S=l2(S_ref), log2_H=H, log2_J=math.log2(d0) + H, family_volume=prop.conds[z].family_volume(), index=0, d_hat=d0, change='cap_only_same_law'))
            for i, (lab, cond, nominal) in enumerate(laws):
                if cond is None: continue
                if (i & 3) == 3: clk.poll('between frontier candidates')
                w = JW.witnesses_of(pk, cond, S_ref=S_ref); conds = dict(prop.conds); conds[z] = cond; newp = JP.Proposal(cards, conds, prop.order, w['B'], w['S'], dict(kind='candidate', label=lab, nominal_log2_C=nominal, packet=pk.sha256, S_witness=w['S_witness'], gamma=w['gamma']), predecessor=inc_ep.index)
                d = self._d_hat(newp); H = JO.H_log2(w['log2_S'], w['log2_B'], log2_eta, self.mode); cands.append(dict(label=lab, is_current=False, prop=newp, log2_B=w['log2_B'], log2_S=w['log2_S'], log2_S_sum_a=w['log2_S_sum_a'], S_witness=w['S_witness'], log2_H=H, log2_J=math.log2(d) + H, family_volume=cond.family_volume(), index=i + 1, d_hat=d, nominal_log2_C=nominal, change=('context_and_law' if fam.get('add') is not None else 'law')))
            win, promoted = JO.select(cands, incumbent, p['promotion_margin']); att.update(incumbent={k: v for k, v in incumbent.items() if k != 'prop'}, candidates=[{k: v for k, v in c.items() if k != 'prop'} for c in cands], rejected_rows=rejected, log2_eta=log2_eta, winner=win['label'], promoted=promoted, log2_Cmin=l2(pk.Cmin), B_tight_log2=l2(B_tight), S_ref_log2=l2(S_ref), scoring_mode=self.mode)
            if promoted:
                clk.poll('before the epoch commit'); newp = win['prop']; committed_at = tnow(); self.joint_bytes += B_.charge(newp.bytes, 'joint epoch %d law' % (len(self.epochs))); self.retained_bytes += newp.bytes
                try: ep = self._commit_epoch(newp, 'promoted:%s' % win['label'], end, B_)
                except BaseException:
                    B_.release(newp.bytes); self.joint_bytes -= newp.bytes; self.retained_bytes -= newp.bytes; raise
                self.updated_vars.add(z); att['committed_epoch'] = ep.index; att['commit_seconds'] = tnow() - committed_at; J_committed = win['log2_J']
            else: J_committed = incumbent['log2_J']
            # held-out off-policy diagnostic of the promoted / best law (NEVER used for the selection; raw moments)
            if self.pilot_store is not None and win.get('prop') is not None and not win.get('is_current'):
                try:
                    st = np.concatenate(self.pilot_store['states']); lw = np.concatenate(self.pilot_store['logW0q']); ids = np.concatenate(self.pilot_store['ids']); held = (ids & 1) == 0; fin = np.isfinite(lw) & (lw > -1000)
                    lq0, _ = prop.logq_bits(st[held & fin]); lq1, _ = win['prop'].logq_bits(st[held & fin]); lw_h = lw[held & fin]       # log2 W_0 / q_0 on the held-out draws; log2 of q_0 / q_1 from the exact count ratios
                    raw = lw_h + (lq0 - lq1) + lw_h                                                                      # log2 [ (W_0 / q_0) x (W_0 / q_1) ] = raw summand of S_0(q_1) estimated off-policy from q_0
                    att['heldout_offpolicy'] = dict(n=int(held.sum()), log2_mean_W0q0_W0q1=(float(raw.max() + math.log2(np.exp2(raw - raw.max()).sum()) - math.log2(raw.size)) if raw.size else None), witness_log2_S=win['log2_S'], note='raw off-policy second-moment estimate of the selected law on the HELD-OUT pilot half; a diagnostic of witness slack / prediction quality, never a bound')
                except Exception as e: att['heldout_offpolicy'] = dict(error=repr(e)[:120])
            T_after = work_end - tnow(); passed, pb = JO.payback(J_committed, incumbent['log2_J'], T_before, T_after); att['payback'] = dict(passed=passed, **pb, J_committed_log2=J_committed, J_incumbent_log2=incumbent['log2_J'], construction_seconds=tnow() - t0)
            att['status'] = 'PROMOTED' if promoted else 'KEPT_INCUMBENT'
            if not passed: self.refinement_ended = 'payback failed after attempt %d' % att['index']
            elif len(self.attempts) + 1 >= p['max_attempts']: self.refinement_ended = 'attempt cap reached'
        except JP.RefusedJoint as e: att.update(status='REFUSED', kind=e.kind, why=str(e.reason)[:200]); self.refinement_ended = 'candidate refused (%s) at attempt %d' % (e.kind, att['index'])
        except CE.Refused as e: att.update(status='REFUSED', kind=e.kind, why=str(e.reason)[:200]); self.refinement_ended = 'candidate refused (%s) at attempt %d' % (e.kind, att['index'])
        except StreamRefused as e: att.update(status='REFUSED', kind=e.kind, why=str(e.reason)[:200]); self.refinement_ended = 'candidate refused (%s) at attempt %d' % (e.kind, att['index'])
        except CE.Defect as e: att.update(status='DEFECT', why=str(e)[:200]); self.refinement_ended = 'candidate construction defect at attempt %d (incumbent kept)' % att['index']; self.mech['candidate_defect'] = str(e)[:200]
        except (ValueError, OverflowError, ZeroDivisionError) as e: att.update(status='NUMERIC', why=repr(e)[:200]); self.refinement_ended = 'numeric failure in candidate construction at attempt %d (incumbent kept)' % att['index']
        except (Deadline, IG.Deadline) as e: att.update(status='REFUSED', kind='DEADLINE', why=str(e)[:200]); self.refinement_ended = 'candidate refused (DEADLINE) at attempt %d' % att['index']
        except AssertionError as e: att.update(status='DEFECT', why=str(e)[:200]); self.refinement_ended = 'candidate invariant failure at attempt %d (incumbent kept)' % att['index']; self.mech['candidate_defect'] = str(e)[:200]
        except Exception as e:                                                                              # DGP5 validity amendment 1: an unexpected exception in a candidate construction keeps the incumbent (typed INTERNAL, traceback recorded)
            import traceback; att.update(status='INTERNAL', why=repr(e)[:200], traceback=traceback.format_exc()[-1500:]); self.refinement_ended = 'internal error in candidate construction at attempt %d (incumbent kept)' % att['index']; self.mech['candidate_defect'] = repr(e)[:200]
        finally:
            if pk is not None: pk.release(); att['packet_released_bytes'] = pk.owned
        att['seconds'] = tnow() - t0; att['ended_offset_s'] = tnow() - self.allowance_start; self.attempts.append(att); self.mech['attempts'] = self.attempts; self.mech['refinement_ended'] = self.refinement_ended
        self.measurements.append(dict(kind='joint_action', action='refine', seconds=att['seconds'], completed=(att.get('status') in ('PROMOTED', 'KEPT_INCUMBENT')), features=dict(status=att.get('status'), promoted=att.get('promoted'))))
        return att
    def can_refine(self):
        return self.stage == 'READY' and not self.all_published() and self.mode != 'seed' and self.pilot is not None and self.refinement_ended is None and len(self.attempts) < self.profile['max_attempts'] and self.allowance_end is not None and tnow() < self.phase_ends['reserve']
    def can_pilot(self): return self.stage == 'READY' and not self.all_published() and self.pilot is None and self.allowance_end is not None and tnow() < self.phase_ends['pilot']
    def diagnostics(self):
        d = super().diagnostics(); multi = sum(1 for e in self.epochs if getattr(e, 'draws_n', 0) > 0) > 1
        if multi:                                                                                                  # DGP6 repair (finding 8): pooled weight statistics across epochs with DIFFERENT caps are meaningless -> removed; the epoch-local ones replace them
            for k in ('X_mean', 'ESS_DIAGNOSTIC', 'largest_share', 'log2_Zhat_over_Ucap_DIAGNOSTIC', 'Z_over_Ucap_EB_DIAGNOSTIC', 'max_log2_X_observed'): d.pop(k, None)
            d['pooled_weight_statistics'] = 'REMOVED: %d epochs with different caps consumed draws; see joint.epoch_weight_statistics' % sum(1 for e in self.epochs if getattr(e, 'draws_n', 0) > 0)
        d['joint'] = dict(mode=self.mode, epochs=[e.record for e in self.epochs], current_epoch=(self.epoch.index if self.epoch else None), epoch_switches=self.epoch_switches, attempts=self.attempts, pilot=self.pilot, refinement_ended=self.refinement_ended, batch_pins=self.batch_pins[:64], batch_pins_overflow=getattr(self, 'batch_pins_overflow', 0), joint_bytes=self.joint_bytes, allowance=self.mech.get('allowance'),
                          epoch_weight_statistics=[dict(epoch=e.index, cap_log2_W0=e.B_eff_log2, draws=getattr(e, 'draws_n', 0), X_mean=((e.sumX / e.draws_n) if getattr(e, 'draws_n', 0) else None), ESS_DIAGNOSTIC=((e.sumX ** 2 / e.sumX2) if getattr(e, 'sumX2', 0.0) > 0 else None), max_X=getattr(e, 'maxX', None), zero_draws=getattr(e, 'zero_n', 0), Z_over_cap_EB_DIAGNOSTIC=(e.zcert.interval() if getattr(e, 'draws_n', 0) else None)) for e in self.epochs]); return d
