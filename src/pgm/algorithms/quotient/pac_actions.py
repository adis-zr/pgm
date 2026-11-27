"""Persistent PAC actions extracted from the accepted v2.13.2 engine (cex/blockres/integrated.py, UNCHANGED and imported) for the unified planner of DENSE_GENERIC_PAC_INTEGRATION_1
(brief section 2). integrated.solve() is a whole-request orchestration; this module exposes its state and its action boundaries without re-implementing any arithmetic:
  structural_routes(st)   -- the accepted precedence chain on the ORIGINAL binding: signed evidence recognition / layered recognition / exact support closure / signed execution / layered
                             execution / ancestral recognition + execution, with the accepted local allowances and the accepted 'an exhausted contract may not start another phase' rule;
                             returns ('COMPLETE', rows) / ('ZERO_EVIDENCE', None) / ('DEADLINE', None) / ('CERTIFICATE_DEFECT', None) / ('CONTINUE', None) and leaves the (possibly reduced) model in st.
  Stream                  -- ONE statistical stream (original / exact-parent / lifted) with resumable preparation stages (integerize -> contract -> constants -> exact enumeration ->
                             float + memory plan + mini-buckets -> exact reverse route -> PAC recovery representation + sampler + widening + Certificate) and committed batches
                             (draw -> weights -> responses block by block -> commit); a scheduling yield between stages or between batches keeps every committed structure; a yield inside a
                             batch retains the generated draws and the unfinished recovery as pending work (same draws, same predictable parameters at commit); a hard cut abandons the batch
                             and CLOSES the stream (its committed prefix stands, no later draw can skip the abandoned batch).
  LiftedStream            -- the section-3 bridge: the accepted max mini-bucket proposal built on the checked UPPER coarse model G_U (coarse_envelope.check_candidate) of an approximate stage over
                             an identity or exact parent; z | c from the exact dyadic decoder rows (lifted_decoder); weights evaluated on the FINE / parent target; responses = exact indicators
                             (identity parent) or the exact decoder values (exact parent); widening extended operation by operation (lifted_widening).
Risk: each stream receives delta_s = delta / 2^s (s = creation index) and divides it over its frozen response inventory (alpha = delta_s / K_s) through the accepted Certificate; the accepted
ZCertificate stays diagnostic. Deterministic rows consume no risk."""
import sys, os, math, json
from fractions import Fraction as F
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); BR_DIR = os.path.join(os.path.dirname(os.path.dirname(HERE)), 'cex', 'blockres')
from pgm.algorithms.block import integrated as IG                      # the accepted engine, unchanged
from pgm.algorithms.block import blockres as BR
from pgm.algorithms.block import support_closure as SC, signed_evidence as SE, layered_contraction as LC, ancestral_response as AR
from pgm.algorithms.quotient import coarse_envelope as CE, lifted_decoder as LD
from pgm.algorithms.block.blockres import tnow, Deadline
inf = math.inf; log2 = math.log2; ldexp = math.ldexp; prod = math.prod


class StreamRefused(Exception):
    def __init__(self, kind, reason): self.kind = kind; self.reason = reason; super().__init__('%s: %s' % (kind, reason))


class RequestState:
    """the immutable original binding + the mutable accepted-route state shared by the deterministic planner and every stream"""
    def __init__(self, model, binding, eps, delta):
        self.model_orig = model; self.binding = binding; self.cards_orig = model['cards']; self.ev_orig = model.get('evidence', {}); n = len(self.cards_orig)
        self.queries_orig = [(x, v) for x in range(n) if x not in self.ev_orig for v in range(self.cards_orig[x])]; self.K_orig = len(self.queries_orig); self.qix_orig = {q: j for j, q in enumerate(self.queries_orig)}
        self.eps = eps; self.delta = delta; self.model = model; self.cards = self.cards_orig; self.ev = self.ev_orig; self.closure = None
        self.queries = list(self.queries_orig); self.qix = dict(self.qix_orig); self.K = self.K_orig
        self.mech = dict(evidence_expansion=dict(status='NOT_RUN'), layered_contraction=dict(status='NOT_RUN'), ancestral_response=dict(status='NOT_RUN'), support_closure=dict(status='NOT_RUN')); self.phases = {}
    def set_reduced(self, cl):
        self.closure = cl; self.model = cl['reduced_model']; self.cards = self.model['cards']; self.ev = {}; n = len(self.cards)
        self.queries = [(x, v) for x in range(n) for v in range(self.cards[x])]; self.qix = {q: j for j, q in enumerate(self.queries)}; self.K = len(self.queries)
    def decode_effective(self, ans_eff, failed_eff, witness):
        """effective rows -> original rows through the accepted closure decoder (deterministic query recovery; nothing without the witness)"""
        if self.closure is None: return dict(ans_eff), list(failed_eff)
        return SC.decode_rows(self.closure, self.cards_orig, self.ev_orig, self.queries_orig, self.qix, ans_eff, failed_eff, witness)


def _row(lo, hi, point, g): return dict(lo=lo, hi=hi, point=point, guarantee=g)


def structural_routes(st, deadline, usable_bytes=IG.USABLE_BYTES, flags=None):
    """the accepted chain before integerization (integrated.solve lines 967-1141), bound to st.model_orig; same precedence, same allowances. Returns (status, rows_orig | None, info)."""
    fl = dict(evidence_expansion=IG.EVIDENCE_EXPANSION_DEFAULT, layered_contraction=IG.LAYERED_CONTRACTION_DEFAULT, ancestral_response=IG.ANCESTRAL_RESPONSE_DEFAULT, support_closure=IG.SUPPORT_CLOSURE_DEFAULT); fl.update(flags or {})
    model = st.model_orig; binding = st.binding; eps = st.eps; ph = st.phases; mech = st.mech; qo = st.queries_orig; K_orig = st.K_orig; info = dict(route=None)
    se_plan = None
    if fl['evidence_expansion']:
        t0 = tnow()
        try: se_plan = SE.recognize(model, qo, binding, min(deadline, t0 + IG.EVIDENCE_RECOGNITION_S)); mech['evidence_expansion'] = dict(status='RECOGNIZED', recognition_s=se_plan.recognition_s, **SE.estimate(se_plan))
        except SE.NotApplicable as e: mech['evidence_expansion'] = dict(status='NOT_APPLICABLE: ' + str(e)[:160], recognition_s=tnow() - t0)
        except SE.RecognitionRefused as e: mech['evidence_expansion'] = dict(status='RECOGNITION_REFUSED: ' + str(e)[:160], recognition_s=tnow() - t0)
        ph['evidence_recognition'] = tnow() - t0
    ar_eligible = fl['ancestral_response'] and se_plan is None; mech['ancestral_response'] = dict(status='DEFERRED: established layered route has precedence' if ar_eligible else 'DISABLED')
    lc_plan = None
    if fl['layered_contraction'] and se_plan is None:
        t0 = tnow()
        try: lc_plan = LC.recognize(model, min(deadline, t0 + IG.LAYERED_RECOGNITION_S), binding); mech['layered_contraction'] = dict(status='RECOGNIZED', recognition_s=lc_plan.recognition_s, structure=lc_plan.structure, volume=lc_plan.volume)
        except LC.NotApplicable as e: mech['layered_contraction'] = dict(status='NOT_APPLICABLE: ' + str(e)[:200], recognition_s=tnow() - t0)
        except LC.RecognitionRefused as e: mech['layered_contraction'] = dict(status='RECOGNITION_REFUSED: ' + str(e)[:200], recognition_s=tnow() - t0)
        ph['layered_recognition'] = tnow() - t0
    if fl['support_closure']:
        t0 = tnow()
        try:
            cl = SC.compile_closure(model, min(deadline, t0 + IG.SUPPORT_CLOSURE_SHARE_S), IG.SUPPORT_CLOSURE_BYTE_CEILING); mech['support_closure'] = cl['stats']
            if not cl['identity']: st.set_reduced(cl)
        except SC.ZeroEvidence as e: mech['support_closure'] = dict(status='ZERO_EVIDENCE: ' + str(e)[:160]); ph['support_closure'] = tnow() - t0; return 'ZERO_EVIDENCE', None, dict(route='support_closure', witness=None)
        except SC.ClosureRefused as e: mech['support_closure'] = dict(status='SKIPPED: ' + str(e)[:160])
        ph['support_closure'] = tnow() - t0
    if se_plan is not None:
        t0 = tnow(); rss_now = SE.rss_bytes_now(); budget_ws = max(0, min(IG.EVIDENCE_WORKSPACE_BUDGET, usable_bytes - rss_now))
        try:
            masses = SE.execute(se_plan, deadline, budget_ws, n_queries=K_orig); ph['evidence_expansion'] = tnow() - t0; rows = SE.dyadic_rows(masses, qo, deadline=deadline)
            for j, r_ in rows.items():
                if (j & 255) == 0 and tnow() >= deadline: raise SE.DeadlineRefused('deadline while validating original answers (nothing published)')
                if not (IG.valid_publication(r_['lo'], r_['hi'], eps) and r_['lo'] <= r_['point'] <= r_['hi']): raise AssertionError('evidence-expansion row %d fails the exact acceptance test' % j)
            mech['evidence_expansion'].update(status='APPLIED', workspace_budget_bytes=budget_ws, **masses.stats); info.update(route='signed_evidence_expansion', Z=str(F(masses.Znum, masses.D)), witness=True)
            if tnow() >= deadline: return 'DEADLINE', None, dict(info, phase='evidence_output')
            return 'COMPLETE', rows, info
        except SE.ZeroEvidence as e: ph['evidence_expansion'] = tnow() - t0; mech['evidence_expansion'].update(status='ZERO_EVIDENCE: ' + str(e)); return 'ZERO_EVIDENCE', None, dict(route='signed_evidence_expansion', witness=False)
        except (SE.ResourceRefused, SE.DeadlineRefused) as e:
            ph['evidence_expansion'] = tnow() - t0; mech['evidence_expansion'].update(status=('RESOURCE_REFUSED: ' if isinstance(e, SE.ResourceRefused) else 'DEADLINE_REFUSED: ') + str(e)[:160])
            if tnow() >= deadline: return 'DEADLINE', None, dict(phase='evidence_expansion')
        except (SE.InvariantFailure, AssertionError) as e: mech['evidence_expansion'].update(status='INVARIANT_FAILURE: ' + str(e)[:160]); return 'CERTIFICATE_DEFECT', None, dict(error=str(e)[:200])
    if lc_plan is not None:
        t0 = tnow(); rss_now = SE.rss_bytes_now(); budget_b = max(0, min(IG.LAYERED_BYTE_CAP, usable_bytes - rss_now)); fc = LC.forecast(lc_plan, deadline - t0); mech['layered_contraction'].update(forecast=fc, byte_budget=budget_b)
        try:
            if fc['forecast_bytes'] > budget_b: raise LC.ResourceRefused('forecast live state %d B > budget %d B' % (fc['forecast_bytes'], budget_b))
            if fc['forecast_kernel_s'] > fc['remaining_s']: raise LC.ResourceRefused('forecast kernel time %.1f s > remaining %.1f s' % (fc['forecast_kernel_s'], fc['remaining_s']))
            R = LC.execute(lc_plan, st.model_orig, deadline, usable_bytes, rss_now); ph['layered_execution'] = tnow() - t0; rows = _rows_from_layered(st, R, lc_plan, deadline, eps)
            mech['layered_contraction'].update(status='APPLIED', certificate=R.certificate); info.update(route='layered_contraction', witness=True, Z_enclosure=dict(lo=str(R.Z_lo), hi=str(R.Z_hi), note='kernel normalizer enclosure x cancelled scalars; NOT an exact rational Z'))
            if tnow() >= deadline: return 'DEADLINE', None, dict(info, phase='layered_output')
            return 'COMPLETE', rows, info
        except LC.ZeroEvidence as e: mech['layered_contraction'].update(status='ZERO_EVIDENCE: ' + str(e)[:160]); return 'ZERO_EVIDENCE', None, dict(route='layered_contraction', witness=False)
        except (LC.ResourceRefused, LC.ExecutorRefused) as e:
            ph['layered_execution'] = tnow() - t0; mech['layered_contraction'].update(status=('RESOURCE_REFUSED: ' if isinstance(e, LC.ResourceRefused) else 'EXECUTOR_REFUSED ') + str(e)[:200])
            if tnow() >= deadline: return 'DEADLINE', None, dict(phase='layered_contraction')
        except AssertionError as e: mech['layered_contraction'].update(status='CERTIFICATE_DEFECT: ' + str(e)[:160]); return 'CERTIFICATE_DEFECT', None, dict(error=str(e)[:200])
    ar_plan = None
    if ar_eligible:
        if tnow() >= deadline: mech['ancestral_response'].update(status='DEADLINE_REFUSED: before ancestral recognition'); return 'DEADLINE', None, dict(phase='ancestral_recognition')
        t0 = tnow()
        try:
            ar_plan = AR.recognize(st.model_orig, deadline, binding, construction_s=IG.ANCESTRAL_CONSTRUCTION_S); rss_now = SE.rss_bytes_now(); budget_b = max(0, min(IG.ANCESTRAL_BYTE_CAP, usable_bytes - rss_now)); fc = AR.forecast(ar_plan, deadline - tnow(), K_orig)
            mech['ancestral_response'] = dict(status='RECOGNIZED', recognition_s=ar_plan.recognition_s, structure=ar_plan.structure, forecast=fc, byte_budget=budget_b)
            if fc['forecast_bytes'] > budget_b: raise AR.ResourceRefused('forecast live state %d B > budget %d B' % (fc['forecast_bytes'], budget_b))
            if fc['forecast_kernel_s'] > fc['remaining_s']: raise AR.ResourceRefused('forecast kernel time %.1f s > remaining %.1f s' % (fc['forecast_kernel_s'], fc['remaining_s']))
        except AR.NotApplicable as e: ar_plan = None; mech['ancestral_response'] = dict(status='NOT_APPLICABLE: ' + str(e)[:200], recognition_s=tnow() - t0)
        except (AR.RecognitionRefused, LC.RecognitionRefused) as e: ar_plan = None; mech['ancestral_response'] = dict(status='RECOGNITION_REFUSED: ' + str(e)[:200], recognition_s=tnow() - t0)
        except AR.ResourceRefused as e: ar_plan = None; mech['ancestral_response'].update(status='RESOURCE_REFUSED: ' + str(e)[:200], recognition_s=tnow() - t0)
        except AR.ZeroMass as e: ar_plan = None; mech['ancestral_response'] = dict(status='ZERO_MASS_REFUSED: ' + str(e)[:200], recognition_s=tnow() - t0)
        ph['ancestral_recognition'] = tnow() - t0
        if tnow() >= deadline: return 'DEADLINE', None, dict(phase='ancestral_recognition')
    if ar_plan is not None:
        t0 = tnow(); rss_now = SE.rss_bytes_now()
        try:
            R = LC.execute(ar_plan, ar_plan.aug, deadline, usable_bytes, rss_now); ph['ancestral_execution'] = tnow() - t0; dec, policies = AR.decode(ar_plan, R, eps, deadline); rows = {}
            for j, (x, v) in enumerate(qo):
                if (j & 255) == 255 and tnow() >= deadline: raise AR.DeadlineRefused('deadline while publishing the original rows (nothing published)')
                L, H, pt = dec[x][v]; g = 'EXACT' if L == H else 'DETERMINISTIC'
                if not (IG.valid_publication(L, H, eps) and L <= pt <= H and max(pt - L, H - pt) <= eps): raise AssertionError('ancestral row %d fails the exact acceptance test' % j)
                rows[j] = _row(L, H, pt, g)
            mech['ancestral_response'].update(status='APPLIED', certificate=R.certificate, point_policies=policies); info.update(route='ancestral_response', witness=True, Z_enclosure=dict(lo=str(R.Z_lo), hi=str(R.Z_hi), note='kernel normalizer enclosure x cancelled scalars incl. the erasure scalar; NOT an exact rational Z'))
            if tnow() >= deadline: return 'DEADLINE', None, dict(info, phase='ancestral_output')
            return 'COMPLETE', rows, info
        except LC.ZeroEvidence as e: mech['ancestral_response'].update(status='ZERO_EVIDENCE: ' + str(e)[:160]); return 'ZERO_EVIDENCE', None, dict(route='ancestral_response', witness=False)
        except (LC.ExecutorRefused, AR.DeadlineRefused) as e:
            ph['ancestral_execution'] = tnow() - t0; mech['ancestral_response'].update(status=('EXECUTOR_REFUSED ' if isinstance(e, LC.ExecutorRefused) else 'DEADLINE_REFUSED: ') + str(e)[:200])
            if tnow() >= deadline: return 'DEADLINE', None, dict(phase='ancestral_response')
        except AssertionError as e: mech['ancestral_response'].update(status='CERTIFICATE_DEFECT: ' + str(e)[:160]); return 'CERTIFICATE_DEFECT', None, dict(error=str(e)[:200])
    return 'CONTINUE', None, info


def _rows_from_layered(st, R, lc_plan, deadline, eps):
    rows = {}; trivial = set(lc_plan.singletons) | set(lc_plan.factorless)
    for j, (x, v) in enumerate(st.queries_orig):
        if (j & 255) == 255 and tnow() >= deadline: raise LC.ExecutorRefused('DEADLINE', 'deadline while compacting the original rows (nothing published)')
        lo, hi = R.intervals[x][v]; pt = R.points[x][v]
        if x in trivial:
            ex = F(1, st.cards_orig[x])
            if not (lo <= ex <= hi): raise AssertionError('layered row %d: trivial exact value outside the executor enclosure' % j)
            lo = hi = pt = ex
        if lo == hi: L, H = lo, hi; g = 'EXACT'
        else:
            L, H = IG.compact_outward(lo, hi); g = 'DETERMINISTIC'
            if not (L <= lo and H >= hi): raise AssertionError('layered row %d: compaction does not enclose' % j)
        if not (IG.valid_publication(L, H, eps) and L <= pt <= H): raise AssertionError('layered row %d fails the exact acceptance test' % j)
        rows[j] = _row(L, H, pt, g)
    return rows


def prepare_sampler_polled(mbp, deadline, plan_log_bytes=None, release_forward=True):
    """DGP3 RF2: the accepted MBFloat.prepare_sampler loop, re-expressed with a deadline poll per elimination step and the log-table bytes ADMITTED before each allocation against the accepted memory plan
    (`plan['log_bytes']`, the amount the cap ladder admitted under the 2.5 GiB usable policy; a step that would exceed the plan by more than 1 MiB refuses MEMORY_POLICY before allocating); produces
    BYTE-IDENTICAL tables (control D29). Returns the log-table bytes built. Raises Deadline / StreamRefused."""
    if mbp.prep is not None: return 0
    if tnow() >= deadline: raise Deadline('sampler preparation (entry)')
    prep = []; cards = mbp.cards; inputs = {id(f) for f in mbp.inputs}; charged = 0
    if release_forward:
        summed = {id(f) for _, q1 in mbp.steps if q1 for f in q1}
        for v, bucket, R in mbp.fwd:
            for f in bucket:
                if id(f) not in inputs and id(f) not in summed and f.scope: f.M = None
    for v, q1 in mbp.steps:
        if tnow() >= deadline: raise Deadline('sampler preparation (step %d)' % len(prep))
        if q1 is None: prep.append((v, None)); continue
        need = sum(f.M.size * 8 for f in q1)
        if plan_log_bytes is not None and charged + need > plan_log_bytes + (1 << 20): raise StreamRefused('MEMORY_POLICY', 'sampler log tables would exceed the admitted plan (%d + %d > %d bytes) at step %d' % (charged, need, plan_log_bytes, len(prep)))
        charged += need; tabs = []
        for f in q1:
            with np.errstate(divide='ignore'): LM = np.where(f.M > 0, np.log2(np.maximum(f.M, 1e-300)), -inf).reshape(-1)
            strides = {}; s_ = 1
            for u in reversed(f.scope): strides[u] = s_; s_ *= cards[u]
            tabs.append((LM, strides, f.scope))
            if release_forward and id(f) not in inputs and f.scope: f.M = None
        prep.append((v, tabs))
    if release_forward: mbp.fwd = []
    mbp.prep = prep
    if tnow() >= deadline: raise Deadline('sampler preparation (exit)')
    return charged


# ---------------------------------------------------------------- ONE statistical stream on a model (original effective model or an exact-quotient parent): integrated.solve lines 1142-1419 as stages + batches
STAGES = ('INIT', 'INTEGERIZED', 'CONTRACTED', 'CONSTANTS', 'PLANNED', 'EXACT_ROUTE_DONE', 'RECOVERY', 'READY', 'COMPLETE', 'CLOSED')


class Stream:
    """kind 'original' (effective model coordinates) or 'exact_parent' (quotient coordinates; decode = exact decoder rows). Every accepted constant / function is integrated.*"""
    def __init__(self, sid, kind, model, queries, seed, eps, delta_s, opts, decode=None, label=None, scale_to_original=F(1)):
        self.sid = sid; self.kind = kind; self.model = model; self.cards = model['cards']; self.ev = model.get('evidence', {}); self.queries = list(queries); self.qix = {q: j for j, q in enumerate(self.queries)}; self.K = len(self.queries)
        self.scale_to_original = F(scale_to_original)                                           # F2: EXACT normalizer scale: Z_original = Z_effective x scale_to_original (the canonical scalar, the closure scalar, ...); restored exactly once at every deterministic exit
        self.seed = seed; self.rng = np.random.default_rng(seed); self.eps = eps; self.delta_s = delta_s; self.opts = opts; self.decode = decode; self.label = label or kind
        self.stage = 'INIT'; self.closed_reason = None; self.stats = dict(elim_work=0, eliminations=0, query_work=0); self.ph = {}; self.mech = dict(kind=kind, sid=sid, delta_s=str(delta_s), seed=seed)
        self.ans = {}; self.pending_rows = {}; self.failed = []; self.witness = False; self.Z = None; self.Z_enclosure = None; self.deterministic_rows = None
        self.pub = {}; self.trace = []; self.draws = 0; self.zero_draws = 0; self.sumX = 0.0; self.sumX2 = 0.0; self.maxX = 0.0; self.maxlogX = -inf; self.t_sample = 0.0; self.t_cert = 0.0; self.t_prep = 0.0; self.batches = 0; self.abandoned = 0
        self.pending = None; self.checkpoints = 0; self.last_width = None; self.retained_bytes = 0; self.stream_refusal = None; self.range_refused = []; self.cdead = None; self.measurements = []; self.endpoints = {}
    # ---- helpers
    OWNED_ATTRS = ('fine_bytes', 'grouped_bytes', 'rmax_bytes', 'joint_bytes')                 # constructor-account charges owned by a stream (sampler log tables live under the memory plan, not this account)
    def _drop_owned(self):
        """DGP5 repair (finding 3): every reference to a constructor-owned array is dropped BEFORE its charge is released, so a released charge never leaves a reachable array (base Stream: nothing owned)"""
        return []
    def _close(self, reason):
        self.stage = 'CLOSED'; self.closed_reason = reason; self.mech['closed'] = reason; B_ = self.opts.get('budget_obj'); self.pending = None
        dropped = self._drop_owned(); released = 0
        if B_ is not None:
            for attr in self.OWNED_ATTRS:
                n = getattr(self, attr, 0)
                if n: B_.release(n); setattr(self, attr, 0); released += n
        self.mech['close_release'] = dict(released_bytes=released, dropped=dropped, rule='references dropped before release (DGP5 finding 3)')
        return 'CLOSED'
    def ready(self): return self.stage == 'READY'
    def live(self): return self.stage not in ('COMPLETE', 'CLOSED')
    # ---- preparation stages (each atomic; a Deadline inside a stage closes the stream: never restarted)
    def prepare(self, deadline, cdead=None, until=None):
        """advance preparation stages until READY / terminal / a scheduling yield BETWEEN stages (tnow() >= until); each stage runs atomically against the hard `deadline` (a Deadline inside a
        stage closes the stream: an atomic native stage is never restarted); cdead = the accepted construction window for contraction + dense recovery"""
        o = self.opts; self.cdead = min(deadline, cdead) if cdead is not None else deadline; until = deadline if until is None else min(until, deadline); t0 = tnow()
        try:
            while self.stage not in ('READY', 'COMPLETE', 'CLOSED'):
                if tnow() >= until: return 'YIELD'
                t0 = tnow(); st = self.stage
                if st == 'INIT': self._integerize()
                elif st == 'INTEGERIZED': self._contract()
                elif st == 'CONTRACTED': self._constants()
                elif st == 'CONSTANTS': self._plan(deadline)
                elif st == 'PLANNED': self._exact_route(deadline)
                elif st == 'EXACT_ROUTE_DONE': self._recovery(deadline)
                elif st == 'RECOVERY': self._sampler(deadline)
                dt = tnow() - t0; self.t_prep += dt; self.measurements.append(dict(kind='pac_stage', stage=st, seconds=dt, completed=True, features=self.stage_features(st)))
            return self.stage
        except Deadline as e:
            self.measurements.append(dict(kind='pac_stage', stage=self.stage, seconds=tnow() - t0, completed=False, censored='DEADLINE', features=self.stage_features(self.stage)))
            return self._close('DEADLINE in preparation stage %s (%s)' % (self.stage, e))
        except IG.RangeRefused as e:
            self.measurements.append(dict(kind='pac_stage', stage=self.stage, seconds=tnow() - t0, completed=False, censored='RANGE', features=self.stage_features(self.stage)))
            return self._close('NUMERIC_RANGE_REFUSED in stage %s: %s' % (self.stage, str(e)[:160]))
        except StreamRefused as e:
            self.measurements.append(dict(kind='pac_stage', stage=self.stage, seconds=tnow() - t0, completed=False, censored=e.kind, features=self.stage_features(self.stage)))
            return self._close('%s in stage %s: %s' % (e.kind, self.stage, str(e.reason)[:160]))
        except (ValueError, OverflowError, ZeroDivisionError) as e:
            self.measurements.append(dict(kind='pac_stage', stage=self.stage, seconds=tnow() - t0, completed=False, censored='NUMERIC', features=self.stage_features(self.stage)))
            return self._close('NUMERIC in stage %s: %s' % (self.stage, repr(e)[:160]))
    def stage_features(self, st):
        f = dict(n=len(self.cards), entries=sum(len(x['values']) for x in self.model['factors']), K=self.K)
        if hasattr(self, 'plan') and self.plan: f.update(log_bytes=self.plan['log_bytes'], forward_bytes=self.plan['forward_bytes'], steps=self.plan.get('steps'))
        if hasattr(self, 'live_blocks'): f.update(blocks=len(self.live_blocks), n_sep=len(self.S))
        if hasattr(self, 'Kq'): f.update(Kq=self.Kq)
        return f
    def _integerize(self):
        fns, const, scale, mult, factorless = BR.integerize(self.model)
        if const == 0: self.Z = F(0); self.witness = False; self.stage = 'COMPLETE'; self.mech['terminal'] = 'ZERO_EVIDENCE'; return
        self.fns = fns; self.const = const; self.scale = scale; self.mult = mult; self.factorless = factorless
        for x in factorless:
            for v in range(self.cards[x]): self.pending_rows[self.qix[(x, v)]] = _row(F(1, self.cards[x]), F(1, self.cards[x]), F(1, self.cards[x]), 'EXACT')
        self.stage = 'INTEGERIZED'
    def _contract(self):
        o = self.opts; self.trace_c = []; self.order = []; t0 = tnow()
        self.live_blocks = BR.contract(self.fns, self.cards, o['table_cap'], self.cdead, self.stats, self.trace_c, self.order); self.ph['contract'] = tnow() - t0; self.step_of = {v: i for i, (v, _) in enumerate(self.trace_c)}
        const_fns = [f for f in self.live_blocks if not f.scope]; self.live_blocks = [f for f in self.live_blocks if f.scope]
        for f in const_fns: self.const *= int(f.arr)
        self.const_fns = const_fns
        if self.const == 0: self.Z = F(0); self.witness = False; self.stage = 'COMPLETE'; self.mech['terminal'] = 'ZERO_EVIDENCE'; return
        self.S = sorted({v for f in self.live_blocks for v in f.scope}); self.mech.update(blocks=len(self.live_blocks), separator_vars=len(self.S), eliminated_vars=len(self.order), const_blocks=len(const_fns), factorless=len(self.factorless), N_S_log2=float(sum(log2(self.cards[v]) for v in self.S)))
        self.stage = 'CONTRACTED'
    def _constants(self):
        o = self.opts
        for b in self.const_fns:
            gb = int(b.arr)
            if gb == 0: continue
            bl = BR.Block(0, b, self.cards)
            for x in b.interior:
                r = BR.recover_query_table(bl, x, self.cards, o['table_cap'] * self.cards[x], self.trace_c, self.step_of, self.cdead, self.stats)
                if r is None: self.failed.append(x); continue
                for v in range(self.cards[x]): val = F(int(r[v]), gb); self.pending_rows[self.qix[(x, v)]] = _row(val, val, val, 'EXACT')
        if not self.live_blocks:
            self.Z = F(self.const * self.mult, self.scale); self.witness = True; self.ans.update(self.pending_rows); self.deterministic_rows = dict(self.ans); self.stage = 'COMPLETE'; self.mech['terminal'] = 'EXACT_CONTRACTION'; return
        N_S = prod(self.cards[v] for v in self.S)
        if N_S <= o['enum_cap']:
            blocks_i = [BR.Block(i, f, self.cards) for i, f in enumerate(self.live_blocks)]; fac_fns = {next(iter(f.facs)): f for f in self.fns}
            for b in blocks_i:
                tabs = []
                for x in b.interior:
                    r = BR.recover_query_table(b, x, self.cards, o['table_cap'] * self.cards[x], self.trace_c, self.step_of, self.cdead, self.stats)
                    if r is None: self.failed.append(x); continue
                    tabs.append((x, r))
                b.set_queries(tabs, self.cards)
            inter = {x for b in blocks_i for x in b.interior if x not in set(self.failed)}; sq = [(x, v) for (x, v) in self.queries if x in set(self.S) or x in inter]
            sep = BR.Separator(blocks_i, self.cards, self.S, sq, 'block', fac_fns, self.cdead); t0 = tnow(); sep.close(next(iter(sep.open))); self.ph['enumerate'] = tnow() - t0; Z = sep.mass
            if Z == 0: self.Z = F(0); self.witness = False; self.stage = 'COMPLETE'; self.mech['terminal'] = 'ZERO_EVIDENCE'; return
            for j, q in enumerate(sq): r = F(int(sep.num[j]), Z); self.ans[self.qix[q]] = _row(r, r, r, 'EXACT')
            self.Z = F(Z * self.const * self.mult, self.scale); self.witness = True; self.ans.update(self.pending_rows); self.deterministic_rows = dict(self.ans); self.stage = 'COMPLETE'; self.mech['terminal'] = 'EXACT_ENUMERATION'; return
        self.stage = 'CONSTANTS'
    def _plan(self, deadline):
        o = self.opts; t0 = tnow(); cache = {}
        def conv(f):
            if id(f) not in cache: cache[id(f)] = IG.ft_from_int(f, self.cards)
            return cache[id(f)]
        self.conv = conv; self.blocks = [conv(f) for f in self.live_blocks]; self.trace_var = {}; self.trace_ft = []
        for st, (v, snap) in enumerate(self.trace_c): self.trace_var[st] = v; self.trace_ft.append([conv(f) for f in snap])
        self.ph['float_convert'] = tnow() - t0; self.pos = {v: i for i, v in enumerate(self.S)}; self.sep_q = [(x, v) for (x, v) in self.queries if x in self.pos]
        base_bytes = sum(f.M.nbytes for f in cache.values()) + sum(f.arr.size * 48 for f in self.fns) + IG.PROCESS_HEADROOM_BYTES + o.get('other_retained_bytes', 0)
        cap_used, plan, tried = IG.memory_plan([b.scope for b in self.blocks], self.cards, o['mb_cap'], base_bytes); self.mech['memory_policy'] = dict(usable_bytes=IG.USABLE_BYTES, base_bytes=base_bytes, cap_requested=o['mb_cap'], cap_used=cap_used, ladder_tried=tried)
        if plan is None: raise StreamRefused('MEMORY_POLICY', 'no mini-bucket cap in the ladder fits the memory policy')
        self.plan = plan; self.cap_used = cap_used; self.base_bytes = base_bytes; t0 = tnow(); self.mbp = IG.MBFloat(self.blocks, self.cards, cap_used, deadline); self.ph['mb_construct'] = tnow() - t0
        self.mech.update(mb_cap=cap_used, mb_logU=self.mbp.logU, mb_splits=self.mbp.splits, mb_unsplit=(self.mbp.splits == 0), sep_queries=len(self.sep_q))
        if self.mbp.logU == -inf: self.Z = F(0); self.witness = False; self.stage = 'COMPLETE'; self.mech['terminal'] = 'ZERO_EVIDENCE'; return
        self.blockfac = {i: [conv(f) for f in self.fns if f.facs <= self.live_blocks[i].facs] for i in range(len(self.blocks))}
        self.iorder = {i: [self.trace_var[st] for st in sorted(self.step_of[u] for u in self.live_blocks[i].interior)] for i in range(len(self.blocks))}
        self.exact_peak = base_bytes + plan['reverse_live_bytes'] + IG.TILE_BUDGET + sum(b.M.nbytes for b in self.blocks) + (64 << 20); self.retained_bytes = base_bytes + plan['forward_bytes']
        self.stage = 'PLANNED'
    def _exact_route(self, deadline):
        """the accepted deterministic reverse route for an UNSPLIT construction (lines 1207-1274); success completes the stream with DETERMINISTIC rows and no statistical risk"""
        o = self.opts; cards = self.cards; qix = self.qix; eps = self.eps; mbp = self.mbp
        if not (mbp.splits == 0 and o.get('exact_route', True) and self.exact_peak <= IG.USABLE_BYTES):
            self.mech['exact_route'] = dict(status=('MEMORY_POLICY_SKIPPED' if mbp.splits == 0 else 'NOT_UNSPLIT')); self.stage = 'EXACT_ROUTE_DONE'; return
        t0 = tnow(); note = None
        try:
            Zft = IG.ft_scalar_product(mbp.scalars); unresolved = 0
            if float(Zft.M) == 0.0: self.Z = F(0); self.witness = False; self.stage = 'COMPLETE'; self.mech['terminal'] = 'ZERO_EVIDENCE'; return
            if Zft.rho >= 1: raise IG.RangeRefused('normalizer enclosure reaches zero (rho_Z = %s)' % float(Zft.rho))
            D = IG.backward_derivatives(mbp, cards, deadline, release=True); Dblk = [D[id(fi)] for fi in mbp.inputs]; pub_exact = {}
            for x in self.S:
                if tnow() >= deadline: raise Deadline('exact_separator')
                bi = min((i for i, b in enumerate(self.blocks) if x in b.scope), key=lambda i: self.blocks[i].M.size); b = self.blocks[bi]
                union, P, e, rho = IG.ft_product([b, Dblk[bi]], cards); axes = tuple(ai for ai, u in enumerate(union) if u != x); nsum = prod(cards[union[ai]] for ai in axes) if axes else 1
                Nx = P.sum(axis=axes) if axes else P; rho = IG.comb(rho, IG.pow1pu(nsum - 1)); Nx, e = IG._rescale(np.asarray(Nx, dtype=float).reshape([cards[x]]), e); Nft = IG.FT((x,), Nx, e, rho)
                for v in range(cards[x]):
                    r_ = IG.interval_ratio(Nft, v, Zft)
                    if r_ is not None and IG.valid_publication(r_[0], r_[1], eps): pub_exact[qix[(x, v)]] = r_
                    else: unresolved += 1
            unrec = []
            for i, b in enumerate(self.blocks):
                if not self.live_blocks[i].interior: continue
                try: Ns = IG.block_numerators_exact(self.blockfac[i], self.iorder[i], Dblk[i], cards, deadline)
                except IG.RangeRefused as e: unrec += list(self.live_blocks[i].interior); continue
                for x in self.live_blocks[i].interior:
                    Nft = Ns.get(x)
                    if Nft is None: unrec.append(x); continue
                    for v in range(cards[x]):
                        r_ = IG.interval_ratio(Nft, v, Zft)
                        if r_ is not None and IG.valid_publication(r_[0], r_[1], eps): pub_exact[qix[(x, v)]] = r_
                        else: unresolved += 1
            xc = None
            if o.get('crosscheck', True):
                IG.BLOCK_CARDS = cards; t1 = tnow(); xc = IG.executor_crosscheck(self.live_blocks, self.S, mbp.order, deadline, 3 * 1024 ** 3); self.ph['executor_crosscheck'] = tnow() - t1; dis = 0; cmp_ = 0; need = 0; missing = 0; rows_ = xc.get('rows')
                for si, x in enumerate(self.S):
                    for v in range(cards[x]):
                        j = qix[(x, v)]
                        if j not in pub_exact: continue
                        need += 1
                        if not rows_ or rows_[si] is None or len(rows_[si]) <= v: missing += 1; continue
                        cmp_ += 1; lo, hi = pub_exact[j]; xlo, xhi = rows_[si][v]
                        if hi < xlo or xhi < lo: dis += 1
                xc = dict(xc, required=need, compared=cmp_, missing=missing, disjoint=dis); xc.pop('rows', None)
                if xc['status'] != 'CERTIFIED' or missing or cmp_ != need: note = 'CROSSCHECK_FAILED'
                elif dis: note = 'INVESTIGATE'
            if note is None:
                compact = {}
                for j, (lo, hi) in pub_exact.items():
                    L, H = IG.compact_outward(lo, hi)
                    if L <= lo and H >= hi and IG.valid_publication(L, H, eps): compact[j] = (L, H)
                self.mech['exact_route'] = dict(status='OK', published=len(compact), unresolved_ratios=unresolved, unrecovered_interior=len(unrec), crosscheck=xc); self.ans.update(self.pending_rows)
                for j, (L, H) in compact.items(): self.ans[j] = _row(L, H, (L + H) / 2, 'DETERMINISTIC')
                self.failed += unrec; self.witness = True; self.Z_enclosure = dict(log2=IG.lg(F(float(Zft.M)) * F(2) ** Zft.e), rho_Z=IG.fup(Zft.rho)); self.deterministic_rows = dict(self.ans); self.ph['exact_route'] = tnow() - t0; self.stage = 'COMPLETE'; self.mech['terminal'] = 'EXACT_ROUTE'; return
            self.mech['exact_route'] = dict(status=note, crosscheck=xc)
        except IG.RangeRefused as e: self.mech['exact_route'] = dict(status='REFUSED: ' + str(e)[:160])
        self.ph['exact_route'] = tnow() - t0
        if any(R.M is None for _, _, R in mbp.fwd):
            t1 = tnow(); self.mbp = IG.MBFloat(self.blocks, cards, self.cap_used, deadline); self.ph['mb_rebuild_for_pac'] = tnow() - t1; self.mech['mb_rebuilt_for_pac'] = True
        self.stage = 'EXACT_ROUTE_DONE'
    def _recovery(self, deadline):
        """PAC recovery representation per block (lines 1275-1310); resumable BETWEEN blocks (self.rec_i)"""
        o = self.opts; cards = self.cards; mbp = self.mbp; blocks = self.blocks; live = self.live_blocks
        if not hasattr(self, 'rec_i'):
            E_z = sum(b.e for b in blocks); self.E_tot = E_z - mbp.E_U
            if abs(self.E_tot) >= 1 << 50: raise StreamRefused('NUMERIC_RANGE', 'exponent sum too large for an exact float')
            self.rec_i = 0; self.rec_order = sorted(range(len(blocks)), key=lambda i: blocks[i].M.size * sum(cards[x] for x in live[i].interior)); self.bytes_used = 0; self.blockQ = []; self.qcols = []; self.qrhos = []; self.shared_blocks = 0; self.dense_blocks = 0; self.skipped = []; self.window_to_shared = 0
        while self.rec_i < len(self.rec_order):
            if tnow() >= deadline: raise Deadline('recovery between blocks')                 # caught by prepare(): closes (resumption between blocks would be natural; kept atomic per stage for this round)
            i = self.rec_order[self.rec_i]; b = blocks[i]; interior = list(live[i].interior)
            if not interior: self.blockQ.append((i, None, [], None)); self.rec_i += 1; continue
            need = b.M.size * sum(cards[x] for x in interior) * 8; done = False
            if self.bytes_used + need <= IG.RECOVERY_BYTE_BUDGET:
                Q = np.zeros((b.M.size, sum(cards[x] for x in interior)), dtype=float); cols = []; rhos = []; c0 = 0; okb = True
                for x in sorted(interior, key=lambda x: len([u for u in interior if self.step_of[u] > self.step_of[x]])):
                    if tnow() >= self.cdead: okb = False; break
                    try: r = IG.recover_query_table_float(b, x, cards, self.trace_ft, self.trace_var, self.step_of, self.cdead, self.stats)
                    except Deadline: okb = False; break
                    if r is None: okb = False; break
                    scale_ = ldexp(1.0, r.e - b.e)
                    for v in range(cards[x]):
                        col = r.M[..., v].reshape(-1) * scale_; pos_ = col[col > 0]
                        if not np.all(np.isfinite(col)) or (pos_.size and float(pos_.min()) < ldexp(1.0, -1000)): raise StreamRefused('NUMERIC_RANGE', 'query-table alignment leaves the normal range')
                        Q[:, c0] = col; cols.append((x, v)); rhos.append(r.rho); c0 += 1
                    del r
                if okb: self.blockQ.append((i, Q, rhos, None)); self.qcols += cols; self.qrhos += rhos; self.bytes_used += need; self.dense_blocks += 1; done = True
                else: del Q
            if not done:
                if tnow() >= self.cdead: self.window_to_shared += 1
                try: sb = IG.SharedBlock(live[i], self.blockfac[i], self.iorder[i], cards, self.pos)
                except IG.RangeRefused as e: self.skipped += interior; self.range_refused.append('block %d: %s' % (i, str(e)[:160])); self.rec_i += 1; continue
                self.blockQ.append((i, None, [sb.rho_f] * len(sb.cols), sb)); self.qcols += sb.cols; self.qrhos += [sb.rho_f] * len(sb.cols); self.shared_blocks += 1
            self.rec_i += 1
        self.failed += self.skipped; self.sq = self.sep_q + self.qcols; self.Kq = len(self.sq); self.qmap = {q: self.qix[q] for q in self.sq}; self.retained_bytes += self.bytes_used
        self.mech.update(Kq=self.Kq, dense_blocks=self.dense_blocks, shared_blocks=self.shared_blocks, recovery_bytes_retained=self.bytes_used, blocks_window_to_shared=self.window_to_shared, shared_blocks_range_refused=self.range_refused)
        self.stage = 'RECOVERY'
    def _sampler(self, deadline):
        """batch size under the memory policy, sampler tables, widening, the Certificate with THIS stream's risk (lines 1311-1351)"""
        o = self.opts; cards = self.cards; mbp = self.mbp; blocks = self.blocks; Kq = self.Kq
        if Kq == 0: raise StreamRefused('NO_COLUMNS', 'no certifiable coordinate (every interior block refused)')
        max_union = max([sb.max_union for _, _, _, sb in self.blockQ if sb is not None] + [1]); max_bps = max([sb.bytes_per_sample for _, _, _, sb in self.blockQ if sb is not None] + [0]); fixed_ws = max([sb.fixed_workspace_bytes for _, _, _, sb in self.blockQ if sb is not None] + [0])
        cert_per_draw = Kq * 8 * 7; batch_used = o['batch']
        while batch_used > 1 and batch_used * cert_per_draw + fixed_ws + min(batch_used, 1) * max_bps > IG.BATCH_BUDGET: batch_used //= 2
        if batch_used * cert_per_draw + fixed_ws + max_bps > IG.BATCH_BUDGET: raise StreamRefused('MEMORY_POLICY', 'even one draw per batch exceeds the batch budget')
        self.batch_used = batch_used; self.chunk = max(1, min(batch_used, (IG.BATCH_BUDGET - batch_used * cert_per_draw - fixed_ws) // max(1, max_bps)))
        t0 = tnow(); self.sampler_bytes = prepare_sampler_polled(mbp, deadline, self.plan['log_bytes']); self.ph['sampler_prep'] = tnow() - t0        # RF2: polled per step, admitted against the accepted memory plan before allocation
        wid = IG.numerical_widening(blocks, mbp, self.qrhos, len(self.S), max(cards), self.E_tot); self.eps_num = IG.fup(wid['eps_num']); rho_X = IG.fup(wid['rho_X']); rho_cap = IG.fup(wid['rho_cap'])
        if wid['delta_log_total'] > F(1, 4): raise StreamRefused('NUMERIC_RANGE', 'log-domain error budget %s too large' % float(wid['delta_log_total']))
        self.mech.update(eps_num=self.eps_num, rho_X=rho_X, rho_cap=rho_cap, E_tot=self.E_tot, batch_used=batch_used, shared_chunk=self.chunk, widening=dict(law=IG.fup(wid['law']), trunc_log2=float(IG.lg(wid['trunc'])) if wid['trunc'] > 0 else None))
        self.logU_capf = IG.up(mbp.logU_f + IG.up(log2(1.0 + rho_cap)) + 2 ** -40); self.cap_tol = IG.up(log2(1.0 + 2 * rho_X)) + 2 ** -40
        self.alpha = float(self.delta_s) / Kq; self.cert = IG.Certificate(Kq, self.alpha, self.eps_num, float(self.eps), o['schedule']); self.zcert = IG.ZCertificate(float(self.delta_s)); self.mech['alpha_per_coordinate'] = self.alpha
        self.mech['cap_units'] = dict(cap_Wint_log2=self.logU_capf + mbp.E_U, E_U=mbp.E_U, E_tot=self.E_tot, unit='W_int = the exact integer product of the live block tables at the separator state; X = W_int(s) / (2^cap_Wint_log2 q(s))')
        self.bLM = []; self.bstr = []; self.bscope = []; self.bMflat = []
        for b in blocks:
            with np.errstate(divide='ignore'): self.bLM.append(np.where(b.M > 0, np.log2(np.maximum(b.M, 1e-300)), -inf).reshape(-1))
            strides = {}; s_ = 1
            for u in reversed(b.scope): strides[u] = s_; s_ *= cards[u]
            self.bstr.append(strides); self.bscope.append(b.scope); self.bMflat.append(b.M.reshape(-1))
        self.sep_pos = np.array([self.pos[x] for (x, v) in self.sep_q], dtype=np.int64); self.sep_val = np.array([v for (x, v) in self.sep_q], dtype=np.int64)
        pac_peak = self.base_bytes + self.plan['log_bytes'] + min(IG.RECOVERY_BYTE_BUDGET, 1 << 62) + IG.BATCH_BUDGET; cache_allow = (max(0, min(IG.RESPONSE_CACHE_BUDGET, IG.USABLE_BYTES - pac_peak)) if self.shared_blocks else 0)
        self.rcache = dict(entries={}, bytes=0, budget=cache_allow); self.retained_bytes = self.base_bytes + self.plan['log_bytes'] + self.bytes_used + batch_used * cert_per_draw + fixed_ws
        fp = self.proposal_fingerprint(deadline=deadline, budget=o.get('budget_obj'))                # DGP5 repair (finding 4): the fingerprint traversal (admitted per chunk, polled) runs BEFORE the final readiness poll
        if tnow() >= deadline: raise Deadline('sampler stage (before READY)')                       # RF2: READY only after a post-stage poll
        self.stage = 'READY'; self.fingerprint = fp
    def _flat_index(self, Sb, i):
        idx = np.zeros(Sb.shape[0], dtype=np.int64)
        for u in self.bscope[i]: idx += Sb[:, self.pos[u]] * self.bstr[i][u]
        return idx
    # ---- batches
    def batch(self, deadline, hard=None):
        """ONE committed batch, or the continuation of the pending one. `deadline` = the scheduling slice end (a yield point between blocks: 'PENDING', draws + completed block responses retained);
        `hard` = the work cutoff (default = deadline): a Deadline raised INSIDE a shared-response evaluation at the hard cut abandons the batch and CLOSES the stream. 'COMMITTED' | 'PENDING' | 'CLOSED' | 'COMPLETE'"""
        if self.stage != 'READY': return self.stage
        hard = deadline if hard is None else hard; t0 = tnow()
        try:
            if self.pending is None:
                Sb, logq, zero_row = self.mbp.sample_batch(self.rng, self.batch_used, self.pos); B = Sb.shape[0]; logz = np.zeros(B); gv = []
                for i in range(len(self.blocks)):
                    idx = self._flat_index(Sb, i); logz += self.bLM[i][idx]; gv.append(self.bMflat[i][idx])
                zero = ~np.isfinite(logz) | zero_row; logX = np.where(zero, -2000.0, (logz - logq - self.logU_capf) + float(self.E_tot)); mx = float(logX[~zero].max()) if (~zero).any() else -inf
                assert mx <= self.cap_tol, 'importance weight exceeds the mini-bucket cap beyond its proved error bound (certificate defect): log2 X = %r > %r' % (mx, self.cap_tol)
                X = np.where(zero, 0.0, np.minimum(1.0, np.exp2(logX))); f = np.zeros((B, self.Kq))
                if len(self.sep_q): f[:, :len(self.sep_q)] = (Sb[:, self.sep_pos] == self.sep_val[None, :]).astype(float)
                self.pending = dict(Sb=Sb, X=X, f=f, gv=gv, zero=zero, mx=mx, bi=0, col=len(self.sep_q), t_spent=0.0)
            P = self.pending; Sb = P['Sb']; X = P['X']; f = P['f']; B = Sb.shape[0]
            while P['bi'] < len(self.blockQ):
                i, Q, rhos, sb = self.blockQ[P['bi']]
                if Q is None and sb is None: P['bi'] += 1; continue
                if Q is not None:
                    idx = self._flat_index(Sb, i); g = P['gv'][i]; Kb = Q.shape[1]
                    with np.errstate(divide='ignore', invalid='ignore'): ratio = np.where(g[:, None] > 0, Q[idx] / np.where(g > 0, g, 1.0)[:, None], 0.0)
                    f[:, P['col']:P['col'] + Kb] = np.clip(ratio, 0.0, 1.0); P['col'] += Kb
                else:
                    if tnow() >= deadline: P['t_spent'] += tnow() - t0; self.t_sample += tnow() - t0; return 'PENDING'           # yield INSIDE the batch: draws and completed block responses retained; the next call resumes HERE with the same draws
                    Kb = len(sb.cols); act = np.nonzero(X > 0)[0]
                    fb, stt = IG.evaluate_shared(sb, Sb, act, self.chunk, hard, self.rcache); f[act, P['col']:P['col'] + Kb] = fb[act]; P['col'] += Kb
                P['bi'] += 1
            # ---- commit: predictable parameters from the pre-batch state inside update_batch (unchanged accepted code)
            self.cert.update_batch(X, f); self.zcert.update_batch(X); self.draws += B; self.zero_draws += int(P['zero'].sum()); self.sumX += float(X.sum()); self.sumX2 += float((X * X).sum()); self.maxX = max(self.maxX, float(X.max())); self.maxlogX = max(self.maxlogX, P['mx'])
            if (X > 0).any(): self.witness = True
            self.batches += 1; self.pending = None; dt = tnow() - t0; self.t_sample += dt; self.measurements.append(dict(kind='pac_batch', seconds=dt + 0.0, completed=True, features=dict(B=B, n_sep=len(self.S), blocks=len(self.blocks), Kq=self.Kq, shared=self.shared_blocks))); return 'COMMITTED'
        except (IG.Deadline, Deadline) as e:
            self.abandoned += 1; self.pending = None; self.t_sample += tnow() - t0; return self._close('batch abandoned at a hard cut inside the shared responses (%s); %d committed batches retained' % (e, self.batches))
        except IG.RangeRefused as e:
            self.abandoned += 1; self.pending = None; self.stream_refusal = str(e); self.t_sample += tnow() - t0; return self._close('NUMERIC_RANGE_REFUSED in a batch: %s; %d committed batches retained' % (str(e)[:120], self.batches))
        except AssertionError as e:
            self.abandoned += 1; self.pending = None; self.defect = str(e)[:200]; self.mech['certificate_defect'] = self.defect; self.t_sample += tnow() - t0; return self._close('CERTIFICATE_DEFECT in a batch (rows withheld): %s' % str(e)[:120])
    FP_CHUNK = 1 << 17                                                                            # fingerprint chunk: 2^17 doubles = 1 MiB per transient copy
    def _fp_table(self, h, LM, deadline, budget, what):
        """hash one table in bounded chunks: each chunk's byte copy is ADMITTED against the constructor account before it is made and released after; the deadline is polled per chunk (DGP5 finding 4)"""
        flat = LM.reshape(-1); n = flat.size
        for off in range(0, max(n, 1), self.FP_CHUNK):
            part = flat[off:off + self.FP_CHUNK]; c = budget.charge(part.nbytes + 64, 'fingerprint chunk of %s' % what) if budget is not None else 0
            try: h.update(part.tobytes())
            finally:
                if c: budget.release(c)
            if deadline is not None and tnow() >= deadline: raise Deadline('proposal fingerprint (%s, entries %d..)' % (what, off))
    def proposal_fingerprint(self, deadline=None, budget=None):
        """sha256 over the sampler's log tables, the cap, the risk, the response inventory and (lifted) the decoder counts; DGP4: + the RMAX profile / plan hash / bound kind when present: the frozen law of this stream.
        DGP5 (finding 4): with `deadline` / `budget` the traversal is polled per chunk and every transient copy admitted (the same hash either way)"""
        import hashlib; h = hashlib.sha256()
        rm = (getattr(self, 'mech', {}) or {}).get('rmax')
        if rm: h.update(json.dumps(dict(bound_kind=rm.get('bound_kind'), profile=rm.get('profile'), plan_sha256=rm.get('plan_sha256'), stages_done=rm.get('stages_done')), sort_keys=True).encode())
        for v, tabs in (self.mbp.prep or []):
            h.update(str(v).encode())
            if tabs:
                for LM, strides, scope in tabs: self._fp_table(h, LM, deadline, budget, 'sampler table of %s' % (v,)); h.update(str(scope).encode())
        h.update(repr((self.logU_capf, self.cap_tol, self.alpha, self.eps_num, getattr(self, 'E_tot', None), len(self.sq))).encode())
        R = getattr(self, 'rows', None)
        if R is not None:
            for k in sorted(R.counts): h.update(str((k, R.counts[k])).encode())
        return h.hexdigest()
    def abandon(self, reason):
        """permanently abandon the pending batch: the stream CLOSES (its committed prefix stands; later draws cannot skip the abandoned batch)"""
        if self.pending is not None: self.abandoned += 1; self.pending = None
        if self.stage == 'READY': self._close('abandoned: ' + reason)
    def check(self):
        """certificate read-out -> publishable parent coordinates (valid_publication), one trace row; returns the width vector"""
        if not hasattr(self, 'cert'): return None
        t0 = tnow(); lo, hi = self.cert.sets(); width = hi - lo
        for j in range(self.Kq):
            if not np.isfinite(width[j]): continue
            L_, H_ = F(float(lo[j])), F(float(hi[j]))
            if not (0 <= L_ <= H_ <= 1): continue
            prev = self.endpoints.get(j)
            if prev is None or (H_ - L_) < (prev[1] - prev[0]): self.endpoints[j] = (L_, H_)                       # F4: every VALID endpoint pair is retained (the anytime-valid confidence set at this check), independently of the epsilon mask; the narrowest seen is kept
            if j not in self.pub and IG.valid_publication(L_, H_, self.eps): self.pub[j] = (L_, H_)                 # the parent-coordinate epsilon mask stays a progress diagnostic (forecasts, all_published)
        unpub = np.array([j for j in range(self.Kq) if j not in self.pub], dtype=int); w = width[unpub] if unpub.size else np.zeros(0); wf = w[np.isfinite(w)]
        self.trace.append(dict(t=tnow(), draws=self.draws, zero_draws=self.zero_draws, X_mean=(self.sumX / max(1, self.draws)), published=len(self.pub), remaining=int(unpub.size), max_remaining_width=(float(wf.max()) if wf.size else 0.0), median_remaining_width=(float(np.median(wf)) if wf.size else 0.0), empty_sets=int((~np.isfinite(w)).sum())))
        self.trace[-1]['valid_endpoints'] = len(self.endpoints); self.checkpoints += 1; self.last_width = width; dt = tnow() - t0; self.t_cert += dt; self.measurements.append(dict(kind='pac_check', seconds=dt, completed=True, features=dict(Kq=self.Kq))); return width
    def max_unresolved_width(self):
        if self.last_width is None: return 2.0
        unpub = [j for j in range(self.Kq) if j not in self.pub]
        if not unpub: return 0.0
        w = self.last_width[unpub]; wf = w[np.isfinite(w)]; return float(wf.max()) if wf.size else 2.0
    def all_published(self): return hasattr(self, 'Kq') and len(self.pub) == self.Kq
    def pac_rows(self):
        """{parent query index: (lo, hi)} of EVERY retained valid confidence endpoint pair (F4: not only the parent-epsilon-publishable ones; the planner decodes them to original coordinates, intersects compatible
        evidence and tests original-coordinate epsilon safety); nothing without the witness; nothing from a stream with a recorded certificate defect"""
        if not self.witness or getattr(self, 'defect', None): return {}
        return {self.qmap[self.sq[j]]: (L, H) for j, (L, H) in self.endpoints.items()}
    def pac_rows_parent_mask(self):
        """diagnostic: the parent-coordinate epsilon-publishable subset (the pre-F4 behaviour)"""
        if not self.witness or getattr(self, 'defect', None): return {}
        return {self.qmap[self.sq[j]]: (L, H) for j, (L, H) in self.pub.items()}
    def exact_rows(self):
        """{parent query index: (lo, hi)} of the EXACT rows recovered deterministically during preparation (factorless variables, constant blocks' interiors): published only with the positive-mass witness, as in the accepted engine (ans.update(pending) under witness); zero risk"""
        if not self.witness: return {}
        return {j: (r['lo'], r['hi']) for j, r in self.pending_rows.items()}
    def Z_original(self):
        """the exact original normalizer when the stream completed deterministically (None otherwise): Z_effective x scale_to_original (F2)"""
        return None if self.Z is None else self.Z * self.scale_to_original
    def diagnostics(self):
        d = dict(kind=self.kind, sid=self.sid, label=self.label, stage=self.stage, closed=self.closed_reason, delta_s=str(self.delta_s), K=self.K, scale_to_original=str(self.scale_to_original), Z_effective=(str(self.Z) if self.Z is not None else None), Z_original=(str(self.Z_original()) if self.Z is not None else None), draws=self.draws, zero_draws=self.zero_draws, batches=self.batches, abandoned=self.abandoned, checkpoints=self.checkpoints, witness=self.witness, t_prep=self.t_prep, t_sample=self.t_sample, t_cert=self.t_cert, published=len(self.pub), retained_bytes=self.retained_bytes, phases=dict(self.ph), measurements=self.measurements)
        if self.draws: d.update(X_mean=self.sumX / self.draws, zero_weight_fraction=self.zero_draws / self.draws, ESS_DIAGNOSTIC=(self.sumX ** 2 / self.sumX2 if self.sumX2 > 0 else 0.0), largest_share=(self.maxX / self.sumX if self.sumX > 0 else None), max_log2_X_observed=self.maxlogX, log2_Zhat_over_Ucap_DIAGNOSTIC=(log2(self.sumX / self.draws) if self.sumX > 0 else None), max_remaining_width=self.max_unresolved_width(), Z_over_Ucap_EB_DIAGNOSTIC=(self.zcert.interval() if hasattr(self, 'zcert') else None), trace=self.trace)
        d['mechanism'] = self.mech; return d


# ---------------------------------------------------------------- the lifted coarse proposal (brief section 3)
def lifted_widening(blocks_C, mbp, fine_fts, n_coarse, maxcard_coarse, n_fine, const_log2_mag, resp_rel, abs_E_tot=0):
    """numerical widening of the LIFTED stream, operation by operation (the accepted numerical_widening's (b), (d) for the coarse proposal verbatim; new: (c') the fine-factor weight, (r) the exact dyadic
    decoder draw's float log, (k) the rounded constants, (e') the final combination; the fine tables' float conversion enters rho_X as a relative factor). Returns the same dict shape."""
    u = IG.UF; L2 = F(145, 100)
    def logerr(mag): return u * (F(mag) + 1)
    rho_tab = IG.comb(*[b.rho for b in blocks_C])                                                            # coarse tables vs exact integers (the CAP concerns the coarse model)
    d_cap = F(0); d_impl = F(0); mag_logq = F(0)
    for Rs in mbp.step_ranges:                                                                               # (b) verbatim from numerical_widening
        if not Rs: mag_logq += F(int(maxcard_coarse).bit_length()); continue
        SR = sum(Rs); q1 = len(Rs); dL = sum(logerr(R) for R in Rs) + u * (q1 + 1) * (SR + q1); rel_p = L2 * dL * (1 + dL) + 4 * u; rel_cond = 2 * rel_p + (maxcard_coarse - 1) * u
        d_cap += rel_cond / F(69, 100); d_impl += logerr(901) + logerr(int(maxcard_coarse).bit_length() + 1) + u * (mag_logq + 910); mag_logq += 901 + int(maxcard_coarse).bit_length() + 1
    SRf = sum(b.R for b in fine_fts); nf = len(fine_fts); d_zf = sum(logerr(b.R) for b in fine_fts) + u * nf * (SRf + nf)        # (c') fine weight: nf log lookups + nf - 1 partial sums of magnitude <= SRf + nf
    d_U = u * mbp.n_scalar * (mbp.n_scalar + int(maxcard_coarse).bit_length() + 2) + logerr(1) * mbp.n_scalar  # (d) verbatim
    d_r = n_fine * logerr(LD.Q_BITS) + u * n_fine * (n_fine * LD.Q_BITS + n_fine)                            # (r) log2 of integer counts in [1, 2^52] (exact dyadic rows; the draw law is exact), n_fine partial sums of magnitude <= n_fine 52
    d_k = 3 * logerr(const_log2_mag) + u * 6 * (const_log2_mag + 4)                                          # (k) three log2 terms of the constant (scale_F, scale_C integers; K_hi significand + exponent) + their two additions and the two roundings of the cap sum
    mags = SRf + nf + mag_logq + n_fine * LD.Q_BITS + mbp.n_scalar + 2 + const_log2_mag + abs_E_tot; d_fin = 5 * u * mags + 5 * u * abs_E_tot        # (e') five additions / subtractions on magnitudes <= mags; the exact integer E_tot enters the float sum once: 5 u |E_tot| (F1)
    d_total = d_zf + d_impl + d_U + d_r + d_k + d_fin
    rho_X_log = L2 * d_total * (1 + d_total); rho_fine = IG.comb(*[b.rho for b in fine_fts]) if fine_fts else F(0); rho_X = (1 + rho_X_log) * (1 + rho_fine) - 1
    rho_cap = (1 + rho_tab) * (1 + L2 * d_cap * (1 + d_cap)) * (1 + mbp.rhoU) * (1 + rho_X_log) - 1
    law = 4 * n_coarse * F(maxcard_coarse + 2, 1 << 53); trunc = n_coarse * F(1, 1 << 900); rho_f = resp_rel + 4 * u
    return dict(rho_X=rho_X, rho_cap=rho_cap, rho_f=rho_f, law=law, trunc=trunc, eps_num=2 * rho_X + rho_f + law + trunc, delta_log_total=d_total, max_log_mag=mags, parts=dict(d_zf=d_zf, d_impl=d_impl, d_U=d_U, d_r=d_r, d_k=d_k, d_fin=d_fin, rho_tab=rho_tab, rho_fine=rho_fine))


def canon_to_model(M):
    """a canonical model (coarse_envelope.Canon) as the executor-shaped dict WITHOUT its scalar (unaries as singleton factors)"""
    return dict(cards=list(M.cards), evidence={}, factors=[dict(scope=(v,), values=list(M.psi[v])) for v in range(len(M.cards))] + [dict(scope=tuple(sc), values=list(vals)) for sc, vals in M.factors])


class LiftedStream(Stream):
    """z lives on the parent canonical model M_par (identity = the base canonical model, or an EXACT quotient parent with stages par_stages); the approximate stage (classes, Cz) over M_par supplies
    c(z), d(z|c) and the upper tables; the response of original coordinate (v, a) is the exact decoder value d_par(a | z_v) (identity: the indicator). Inventory = every (v, a) of the retained fine variables."""
    def __init__(self, sid, M_fine, M_par, par_stages, classes, Cz, seed, eps, delta_s, opts, label=None, scale_to_original=None, envelope='G1'):
        model = canon_to_model(M_par); queries = [(v, a) for v in range(len(M_fine.cards)) for a in range(M_fine.cards[v])]
        super().__init__(sid, 'lifted', model, queries, seed, eps, delta_s, opts, label=label or 'lifted', scale_to_original=(M_par.scalar if scale_to_original is None else scale_to_original)); self.M_fine = M_fine; self.M_par = M_par; self.par_stages = par_stages; self.classes = classes; self.Cz = Cz; self.n_par = len(M_par.cards); self.envelope = envelope; self.grouped = None; self.mech['envelope'] = envelope
        self.mech.update(parent_exact_stages=len(par_stages), coarse_cards=list(Cz.ccards), parent_cards=list(M_par.cards)); self.rmax = None; self.rmax_bytes = 0; self.rmax_midpoint = None; self.rmax_allowance_end = None; self.bound_kind = ('target_over_actual_decoder' if envelope == 'RMAX' else 'target_over_upper_times_ideal_decoder'); self.mech['bound_kind'] = self.bound_kind
    def stage_features(self, st):
        return dict(n=self.n_par, entries=sum(len(x['values']) for x in self.model['factors']), K=self.K, coarse_states=sum(self.Cz.ccards), kind='lifted')
    def _drop_owned(self):
        """DGP5 (finding 3): the fine float / log tables, the grouped tables and the RMAX compile object (its active / closed / packed arrays) are dereferenced before their charges are released; the committed certificate,
        the decoder rows (still charged; counted by the ledger identity), the sampler log tables (memory plan) and every diagnostic record stay"""
        dropped = []
        for attr in ('fine', 'fLM', 'fstr', 'fscope'):
            if getattr(self, attr, None): setattr(self, attr, []); dropped.append(attr)
        if getattr(self, 'grouped', None) is not None: self.grouped = None; dropped.append('grouped')
        comp = getattr(self, 'rmax', None)
        if comp is not None: comp.active = []; comp.closed = []; comp.packed = []; self.rmax = None; dropped.append('rmax')
        return dropped
    def prepare(self, deadline, cdead=None, until=None):
        until = deadline if until is None else min(until, deadline); t0 = tnow()
        if self.envelope == 'RMAX':
            # DGP4: the RMAX route's stages run against the EFFECTIVE preparation deadline min(hard, allowance). DGP5 repair (finding 5): the allowance has ONE stored ABSOLUTE end, fixed at the first entry together with
            # the midpoint; a later call with a longer `until` cannot reopen it; an exhausted allowance before READY is a TYPED refusal (the primary is preserved), never a YIELD that resumes later
            if self.rmax_allowance_end is None: self.rmax_allowance_end = until; self.mech['rmax_allowance'] = dict(entry_offset_s=0.0, effective_allowance_s=until - tnow(), midpoint_s=0.5 * max(0.0, until - tnow()), absolute_end=self.rmax_allowance_end, rule='absolute end + midpoint persist across calls (DGP5 finding 5)')
            if self.rmax_midpoint is None: self.rmax_midpoint = tnow() + 0.5 * max(0.0, until - tnow())                  # ONE midpoint, set once (an injected earlier midpoint is honoured: control D41)
            eff = min(deadline, self.rmax_allowance_end); until = min(until, self.rmax_allowance_end)
            if self.stage not in ('READY', 'COMPLETE', 'CLOSED') and tnow() >= self.rmax_allowance_end:
                self.measurements.append(dict(kind='lifted_stage', stage=self.stage, seconds=0.0, completed=False, censored='ALLOWANCE', features=self.stage_features(self.stage))); return self._close('ALLOWANCE in lifted stage %s: the optional preparation allowance (absolute end) expired before READY (not reopened)' % self.stage)
        else: eff = deadline
        try:
            while self.stage not in ('READY', 'COMPLETE', 'CLOSED'):
                if tnow() >= until:
                    if self.envelope == 'RMAX' and tnow() >= self.rmax_allowance_end: self.measurements.append(dict(kind='lifted_stage', stage=self.stage, seconds=0.0, completed=False, censored='ALLOWANCE', features=self.stage_features(self.stage))); return self._close('ALLOWANCE in lifted stage %s: the optional preparation allowance (absolute end) expired between stages (not reopened)' % self.stage)
                    return 'YIELD'
                t0 = tnow(); st = self.stage
                if st == 'INIT': self._l_decoder(eff)
                elif st == 'INTEGERIZED': self._l_coarse_proposal(eff)
                elif st == 'CONTRACTED': self._l_fine_tables(eff)
                elif st == 'CONSTANTS': self._l_sampler(eff)
                dt = tnow() - t0; self.t_prep += dt; self.measurements.append(dict(kind='lifted_stage', stage=st, seconds=dt, completed=True, features=self.stage_features(st)))
            return self.stage
        except Deadline as e: self.measurements.append(dict(kind='lifted_stage', stage=self.stage, seconds=tnow() - t0, completed=False, censored='DEADLINE', features=self.stage_features(self.stage))); return self._close('DEADLINE in lifted stage %s (%s)' % (self.stage, e))
        except (IG.RangeRefused, CE.Refused) as e: self.measurements.append(dict(kind='lifted_stage', stage=self.stage, seconds=tnow() - t0, completed=False, censored='RANGE', features=self.stage_features(self.stage))); return self._close('REFUSED in lifted stage %s: %s' % (self.stage, str(e)[:160]))
        except StreamRefused as e: self.measurements.append(dict(kind='lifted_stage', stage=self.stage, seconds=tnow() - t0, completed=False, censored=e.kind, features=self.stage_features(self.stage))); return self._close('%s in lifted stage %s: %s' % (e.kind, self.stage, str(e.reason)[:160]))
        except (ValueError, OverflowError, ZeroDivisionError) as e: self.measurements.append(dict(kind='lifted_stage', stage=self.stage, seconds=tnow() - t0, completed=False, censored='NUMERIC', features=self.stage_features(self.stage))); return self._close('NUMERIC in lifted stage %s: %s' % (self.stage, repr(e)[:160]))
    def _l_decoder(self, deadline):
        clk = CE.Clock(deadline, {}); B = self.opts.get('budget_obj') or CE.Budget(CE.CONSTRUCTOR_BYTES); self.rows = LD.build_rows(self.M_par, self.classes, self.Cz, clk, B); self.retained_bytes += self.rows.bytes
        self.mech.update(kappa_compact=self.rows.K.record(), kappa_float=self.rows.kappa_float, kappa_log2=self.rows.K.log2_hi(), kappa_v_max_log2=max(float(IG.lg(kv)) for kv in self.rows.kappa_v) if self.rows.kappa_v else None); self.stage = 'INTEGERIZED'
    def _l_coarse_proposal(self, deadline):
        """the accepted max mini-bucket proposal on the checked UPPER coarse model (no block contraction: every coarse variable is sampled); DGP3: envelope G2 / G3 replaces the per-factor U tables by the
        grouped joint maxima (grouped_envelope; lemma G), charged and polled; G1 = the DGP2 per-factor envelope"""
        o = self.opts
        if self.envelope == 'RMAX': self.blocks_C, self.ccards = self._rmax_upper_model(deadline); self.scale_C = 1; self.S = list(range(len(self.ccards))); self.pos = {v: v for v in self.S}
        else:
            if self.envelope != 'G1':
                from pgm.algorithms.quotient import grouped_envelope as GE; t0 = tnow(); clk = CE.Clock(deadline, {}); B_ = o.get('budget_obj') or CE.Budget(CE.CONSTRUCTOR_BYTES)
                groups, gscopes = GE.plan_groups(self.M_par, self.Cz, self.envelope); tables, self.grouped_bytes = GE.grouped_upper_tables(self.M_par, self.classes, self.Cz, groups, gscopes, clk, B_)
                self.grouped = dict(groups=groups, scopes=gscopes, tables=tables); cm = GE.grouped_coarse_model(self.M_par, self.Cz, tables); self.ph['grouped_envelope'] = tnow() - t0
                self.mech['grouped_envelope'] = dict(level=self.envelope, groups=len(groups), grouped_pairs=sum(1 for g in groups if len(g) >= 2), max_joint_scope=max(len(S) for S in gscopes), cells=sum(len(U) for _, U in tables), seconds=self.ph['grouped_envelope'], charged_bytes=self.grouped_bytes); self.retained_bytes += self.grouped_bytes
            else: cm = CE.coarse_model(self.M_par, self.Cz, 1)
            fns_C, const_C, scale_C, mult_C, factorless_C = BR.integerize(cm)
            if const_C == 0 or factorless_C: raise StreamRefused('SUPPORT', 'upper coarse model has a zero nullary factor or a factorless coarse variable')
            self.scale_C = scale_C; self.blocks_C = [IG.ft_from_int(f, cm['cards']) for f in fns_C]; self.ccards = list(cm['cards']); self.S = list(range(len(self.ccards))); self.pos = {v: v for v in self.S}
        base_bytes = sum(f.M.nbytes for f in self.blocks_C) + o.get('other_retained_bytes', 0) + IG.PROCESS_HEADROOM_BYTES
        cap_used, plan, tried = IG.memory_plan([b.scope for b in self.blocks_C], self.ccards, o['mb_cap'], base_bytes); self.mech['memory_policy'] = dict(cap_requested=o['mb_cap'], cap_used=cap_used, ladder_tried=tried, base_bytes=base_bytes)
        if plan is None: raise StreamRefused('MEMORY_POLICY', 'no mini-bucket cap in the ladder fits the memory policy (coarse proposal)')
        self.plan = plan; self.cap_used = cap_used; self.base_bytes = base_bytes; t0 = tnow(); self.mbp = IG.MBFloat(self.blocks_C, self.ccards, cap_used, deadline); self.ph['mb_construct'] = tnow() - t0
        self.mech.update(mb_cap=cap_used, mb_logU=self.mbp.logU, mb_splits=self.mbp.splits, coarse_variables=len(self.S))
        if self.mbp.logU == -inf: self.Z = F(0); self.witness = False; self.stage = 'COMPLETE'; self.mech['terminal'] = 'ZERO_MASS_PROVED_BY_UPPER_MODEL'; return   # an exact checked upper zero proves zero target mass
        self.retained_bytes += plan['forward_bytes']; self.stage = 'CONTRACTED'
    def _rmax_upper_model(self, deadline):
        """DGP4: residual MAX compilation on H = W_0 / r (the ACTUAL dyadic rows, frozen in _l_decoder), ONE midpoint for MAX stages, closure, independent checks, upward packing, then the bridge BR.Fn -> IG.ft_from_int
        with each table's packed exponent added to FT.e (carried into MBFloat.E_U); nullary constants folded into the smallest coarse table; unit unaries for coarse variables no table mentions. Returns (blocks_C, ccards).
        Every byte is owned by the compile object until it transfers to self.rmax_bytes exactly once (released by _close); on ANY failure the compile object releases everything it owns."""
        from pgm.algorithms.quotient import residual_max_envelope as RM, grouped_envelope as GE
        o = self.opts; B_ = o.get('budget_obj') or CE.Budget(CE.CONSTRUCTOR_BYTES); clk = CE.Clock(deadline, {}); prof = dict(o.get('rmax_profile') or RM.PROFILE_PRODUCTION); t0 = tnow(); comp = RM.RMAXCompile(self.M_par, self.classes, self.Cz, self.rows, prof, B_, clk)
        try:
            comp.build_sources(); groups, _ = GE.plan_groups(self.M_par, self.Cz, 'G2'); comp.build_seeds(groups); comp.set_order(); self.ph['rmax_sources_seeds'] = tnow() - t0
            if tnow() >= deadline: raise Deadline('RMAX after sources / seeds')
            t1 = tnow(); comp.run_stages(self.rmax_midpoint if self.rmax_midpoint is not None else deadline); self.ph['rmax_stages'] = tnow() - t1
            t2 = tnow(); comp.closure(); comp.pack(); self.ph['rmax_closure_pack'] = tnow() - t2; pk = RM.check_packing(comp.closed, comp.packed, clk)         # DGP5 (finding 1): closure / packing / checker admitted + polled
            if not pk['ok']: raise CE.Defect('RMAX packing check failed: %s' % pk)
            if not comp.record()['checker']['all_ok']: raise CE.Defect('RMAX stage checker rejected a stage')
            if tnow() >= deadline: raise Deadline('RMAX after closure / packing')
            # bridge: one Fn per packed table (axes -> coarse variables, sorted), ints >= 0, then FT with the packed exponent added; coarse variables without a table get a unit unary
            ccards = list(self.Cz.ccards); blocks = []; touched = set(); E_pack = 0
            for P in comp.packed:
                scope = tuple(a >> 1 for a in P['axes']); assert tuple(sorted(scope)) == scope and len(set(scope)) == len(scope)
                if (max(int(x).bit_length() for x in P['ints'].reshape(-1)) if P['ints'].size else 0) > 4096: raise StreamRefused('BITS', 'a packed RMAX mantissa exceeds the bit cap')
                if abs(P['E']) >= 1 << 40: raise StreamRefused('NUMERIC_RANGE', 'a packed RMAX exponent %d is out of the admitted range' % P['E'])
                comp.owned[0] += B_.charge(int(P['ints'].size) * 8 + 128, 'RMAX adapter float table %d' % P['tid']); fn = BR.Fn(scope, np.asarray(P['ints'], dtype=object), [P['tid']], []); ft = IG.ft_from_int(fn, ccards); ft.e += int(P['E']); E_pack += int(P['E']); blocks.append(ft); touched |= set(scope)     # DGP5 (finding 1): the adapter buffer admitted before allocation, owned by the compile object
            for v in range(len(ccards)):
                if v not in touched: blocks.append(IG.ft_from_int(BR.Fn((v,), np.ones(ccards[v], dtype=object), [], []), ccards))
            if not blocks: raise StreamRefused('SUPPORT', 'RMAX produced no coarse table (no coarse variable)')
            self.rmax = comp; self.rmax_bytes = comp.transfer(); self.retained_bytes += self.rmax_bytes; rec = comp.record(); rec.update(seconds_total=tnow() - t0, packed_exponent_sum=E_pack, phases={k: v for k, v in self.ph.items() if k.startswith('rmax')}); self.mech['rmax'] = rec
            return blocks, ccards
        except BaseException as e:
            comp.release_all(); self.mech['rmax_refusal'] = dict(kind=(getattr(e, 'kind', None) or type(e).__name__), reason=str(getattr(e, 'reason', e))[:160], stages_done=comp.stages_done, owned_released=True)
            if isinstance(e, RM.RefusedRMAX): raise StreamRefused(e.kind, e.reason)
            if isinstance(e, CE.Defect): self.defect = 'RMAX construction defect (optional route closed, nothing published from it): %s' % str(e)[:160]; self.mech['construction_defect'] = self.defect; raise StreamRefused('DEFECT', str(e)[:160])   # an OPTIONAL construction's internal defect closes THIS stream typed; the request continues on the incumbent (brief section 4)
            raise
    def _l_fine_tables(self, deadline):
        """float tables of the FINE (parent) target: W_int(z) = scale_F x W'(z); response matrices D_v (parent state -> original coordinate response)"""
        fns_F, const_F, scale_F, mult_F, factorless_F = BR.integerize(self.model)
        if const_F == 0: self.Z = F(0); self.witness = False; self.stage = 'COMPLETE'; self.mech['terminal'] = 'ZERO_EVIDENCE'; return
        self.scale_F = scale_F; B_ = self.opts.get('budget_obj'); self.fine = []
        for i, f in enumerate(fns_F):                                                           # RF2: polled per factor, float tables admitted before conversion
            if (i & 15) == 15 and tnow() >= deadline: raise Deadline('fine tables (factor %d)' % i)
            if B_ is not None: self.fine_bytes = getattr(self, 'fine_bytes', 0) + B_.charge(np.asarray(f.arr).size * 16 + 128, 'fine float + log table (factor %d)' % i)
            self.fine.append(IG.ft_from_int(f, self.cards))
        self.E_fine = sum(b.e for b in self.fine); self.fLM = []; self.fstr = []; self.fscope = []
        for i, b in enumerate(self.fine):
            if (i & 15) == 15 and tnow() >= deadline: raise Deadline('fine log tables (factor %d)' % i)
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
        self.Kq = col; self.resp_rel = resp_rel; self.sq = list(self.queries); self.qmap = {q: self.qix[q] for q in self.sq}
        self.retained_bytes += sum(b.M.nbytes for b in self.fine) + sum(d.nbytes for d in self.Dm)
        if tnow() >= deadline: raise Deadline('fine tables (before CONSTANTS)')
        self.stage = 'CONSTANTS'
    def _l_sampler(self, deadline):
        o = self.opts; mbp = self.mbp; Kq = self.Kq
        cert_per_draw = Kq * 8 * 7 + 8 * self.n_par * 3; batch_used = o['batch']
        while batch_used > 1 and batch_used * cert_per_draw > IG.BATCH_BUDGET: batch_used //= 2
        self.batch_used = batch_used; t0 = tnow(); self.sampler_bytes = prepare_sampler_polled(mbp, deadline, self.plan['log_bytes']); self.ph['sampler_prep'] = tnow() - t0      # RF2
        self.E_tot = self.E_fine - mbp.E_U
        if abs(self.E_tot) >= 1 << 50: raise StreamRefused('NUMERIC_RANGE', 'exponent sum too large for an exact float')
        # the constant scale_F / scale_C x K_hi in the LOG domain (F1 / compact kappa): three log2 terms (two integers, one compact significand) each within 1 ulp; their magnitudes enter the widening as part (k)
        K = self.rows.K; t_num = math.log2(self.scale_F)
        if self.bound_kind == 'target_over_actual_decoder': t_den = 0.0; t_K = 0.0; const_log2 = t_num; const_mag = int(abs(t_num)) + 4; self.mech['const_log2'] = const_log2; self.mech['kappa_applied'] = False          # DGP4: W_0 <= U r directly; C_int = scale_F B; no scale_C divisor (packed integers carry their exponents in E_U), no kappa
        else: t_den = math.log2(self.scale_C); t_K = math.log2(K.hi_m) + K.hi_e; const_log2 = (t_num - t_den) + t_K; const_mag = int(abs(t_num) + abs(t_den) + abs(t_K)) + 4; self.mech['const_log2'] = const_log2; self.mech['kappa_compact'] = K.record(); self.mech['kappa_log2_hi'] = t_K
        wid = lifted_widening(self.blocks_C, mbp, self.fine, len(self.S), max(self.ccards), self.n_par, const_mag, self.resp_rel, abs_E_tot=abs(self.E_tot))    # 5 u |E_tot| and the constant terms are INSIDE d_total before rho_X / rho_cap / eps_num are derived (F1)
        if wid['delta_log_total'] > F(1, 4): raise StreamRefused('NUMERIC_RANGE', 'log-domain error budget %s too large' % float(wid['delta_log_total']))
        self.eps_num = IG.fup(wid['eps_num']); rho_X = IG.fup(wid['rho_X']); rho_cap = IG.fup(wid['rho_cap']); const_slack = IG.fup(wid['parts']['d_k'])            # the consumed constant carries its own proved log error (part k) outward
        self.logU_capf = IG.up(IG.up(IG.up(mbp.logU_f + IG.up(log2(1.0 + rho_cap))) + IG.up(const_log2 + const_slack)) + 2 ** -40); self.cap_tol = IG.up(log2(1.0 + 2 * rho_X)) + 2 ** -40
        cap_Wint_log2 = self.logU_capf + mbp.E_U                                              # RF3: the batch computes X = 2^(logz + E_fine - logq - logr - logU_capf - E_U) = W_int / (2^(logU_capf + E_U) q): the cap in W_int units is 2^(logU_capf + E_U)
        self.mech.update(eps_num=self.eps_num, rho_X=rho_X, rho_cap=rho_cap, E_tot=self.E_tot, E_U=mbp.E_U, E_fine=self.E_fine, batch_used=batch_used, widening={k: (float(v) if isinstance(v, F) else v) for k, v in wid.items() if k != 'parts'}, widening_parts={k: float(v) for k, v in wid['parts'].items()}, scale_ratio_log2=(t_num - t_den), cap_log2_total=cap_Wint_log2,
                         cap_units=dict(cap_Wint_log2=cap_Wint_log2, unit='W_int = scale_F x W_par (parent canonical target without its scalar); X = W_int(z) / (2^cap_Wint_log2 q(z))', cap_original_units_log2=(cap_Wint_log2 - float(IG.lg(F(self.scale_F)))) if self.scale_F > 0 else None, legacy_logU_capf_plus_E_tot=self.logU_capf + self.E_tot, note='DGP2 records reported logU_capf + E_tot (a unit error of E_fine - 2 E_U bits); B / Z and Z_U / Z need an independent denominator; not computed in production'))
        self.alpha = float(self.delta_s) / Kq; self.cert = IG.Certificate(Kq, self.alpha, self.eps_num, float(self.eps), o['schedule']); self.zcert = IG.ZCertificate(float(self.delta_s)); self.mech['alpha_per_coordinate'] = self.alpha
        self.retained_bytes += self.plan['log_bytes'] + batch_used * cert_per_draw
        fp = self.proposal_fingerprint(deadline=deadline, budget=o.get('budget_obj'))                # DGP5 repair (finding 4): fingerprint (admitted per chunk, polled) BEFORE the final readiness poll
        if tnow() >= deadline: raise Deadline('lifted sampler stage (before READY)')               # RF2
        self.stage = 'READY'; self.fingerprint = fp
    def _flat_fine(self, z, i):
        idx = np.zeros(z.shape[0], dtype=np.int64)
        for u in self.fscope[i]: idx += z[:, u] * self.fstr[i][u]
        return idx
    def batch(self, deadline, hard=None):
        """one committed batch: c ~ q_C (accepted sampler), z | c from the exact dyadic rows, X = W_int(z) / (cap_total q_C(c) r(z | c)), responses D_v[z_v]; no shared path exists here, so a batch is
        atomic: a scheduling slice end never interrupts it (it is finished); only the HARD work cutoff abandons it (and closes the stream)"""
        if self.stage != 'READY': return self.stage
        hard = deadline if hard is None else hard; t0 = tnow()
        try:
            Sb, logq, zero_row = self.mbp.sample_batch(self.rng, self.batch_used, self.pos); B = Sb.shape[0]; z = np.zeros((B, self.n_par), dtype=np.int64); logr = np.zeros(B); R = self.rows
            for v in range(self.n_par):
                u = self.rng.integers(0, LD.Q, size=B, dtype=np.int64); cv = Sb[:, v]
                for c in np.unique(cv):
                    rows = np.nonzero(cv == c)[0]; cum = np.asarray(R.cum[(v, int(c))], dtype=np.int64); k = np.searchsorted(cum, u[rows], side='right'); mem = np.asarray(R.members[v][int(c)], dtype=np.int64); cnt = np.asarray(R.counts[(v, int(c))], dtype=np.int64)
                    z[rows, v] = mem[k]; logr[rows] += np.log2(cnt[k].astype(float)) - LD.Q_BITS
            if tnow() >= hard: raise Deadline('lifted batch at the hard work cutoff')
            logz = np.zeros(B)
            if getattr(self, 'mutant_surrogate', False):                                                    # CONTROLS ONLY (never set in production): the weight of the UPPER surrogate instead of the fine target W(z): G_U(c) d(z|c) (G1-G3) or U(c) r(z|c) (RMAX)
                for i in range(len(self.blocks_C)):
                    b = self.blocks_C[i]; idx = np.zeros(B, dtype=np.int64); st = {}; s_ = 1
                    for u in reversed(b.scope): st[u] = s_; s_ *= self.ccards[u]
                    for u in b.scope: idx += Sb[:, u] * st[u]
                    with np.errstate(divide='ignore'): logz += np.log2(b.M.reshape(-1)[idx]) + b.e
                if self.bound_kind == 'target_over_actual_decoder': logz += logr + float(IG.lg(F(self.scale_F))) - self.E_fine          # U(c) r(z|c) in W_int units (no scale_C, no d)
                else:
                    for v in range(self.n_par): logz += np.log2(np.array([float(self.Cz.d[v][a]) for a in z[:, v]]))
                    logz += float(IG.lg(F(self.scale_F, self.scale_C))) - self.E_fine
            else:
                for i in range(len(self.fine)): logz += self.fLM[i][self._flat_fine(z, i)]
            zero = ~np.isfinite(logz) | zero_row; logX = np.where(zero, -2000.0, (logz - logq - logr - self.logU_capf) + float(self.E_tot)); mx = float(logX[~zero].max()) if (~zero).any() else -inf
            assert mx <= self.cap_tol, 'lifted importance weight exceeds the certified cap beyond its proved error bound (certificate defect): log2 X = %r > %r' % (mx, self.cap_tol)
            X = np.where(zero, 0.0, np.minimum(1.0, np.exp2(logX))); f = np.zeros((B, self.Kq))
            for v in range(self.n_par): f[:, self.col0[v]:self.col0[v] + self.M_fine.cards[v]] = self.Dm[v][z[:, v]]
            self.cert.update_batch(X, f); self.zcert.update_batch(X); self.draws += B; self.zero_draws += int(zero.sum()); self.sumX += float(X.sum()); self.sumX2 += float((X * X).sum()); self.maxX = max(self.maxX, float(X.max())); self.maxlogX = max(self.maxlogX, mx)
            if (X > 0).any(): self.witness = True
            self.batches += 1; dt = tnow() - t0; self.t_sample += dt; self.measurements.append(dict(kind='lifted_batch', seconds=dt, completed=True, features=dict(B=B, n_coarse=len(self.S), n_fine=self.n_par, fine_factors=len(self.fine), Kq=self.Kq))); return 'COMMITTED'
        except (IG.Deadline, Deadline) as e: self.abandoned += 1; self.t_sample += tnow() - t0; return self._close('lifted batch abandoned at a hard cut (%s); %d committed batches retained' % (e, self.batches))
        except IG.RangeRefused as e: self.abandoned += 1; self.stream_refusal = str(e); self.t_sample += tnow() - t0; return self._close('NUMERIC_RANGE_REFUSED in a lifted batch: %s' % str(e)[:120])
        except AssertionError as e: self.abandoned += 1; self.defect = str(e)[:200]; self.mech['certificate_defect'] = self.defect; self.t_sample += tnow() - t0; return self._close('CERTIFICATE_DEFECT in a lifted batch (rows withheld): %s' % str(e)[:120])
    def upper_weight_fn(self):
        """exact upper weight of THIS stream's upper model at the coarse state c -- G1 / G2 / G3: G_U(c) (bounds W_0 / d, times the scalar); RMAX: the PACKED U(c) (bounds W_0 / r, no scalar); oracle / controls"""
        if self.envelope == 'RMAX' and self.rmax is not None: return self.rmax.packed_upper_weight
        if self.grouped is not None:
            from pgm.algorithms.quotient import grouped_envelope as GE; return GE.grouped_upper_weight(self.M_par, self.Cz, self.grouped['tables'])
        return lambda c: LD.upper_weight(self.M_par, self.Cz, c)
    def weight_oracle(self, z_tuple):
        """controls only: the exact analyzed X(z) = W_int(z) / (cap_total_exact q_an(c) r(z|c)) numerator pieces -- exact W'(z), G_U'(c), d(z|c), r(z|c) as Fractions"""
        c = tuple(self.classes[v][z_tuple[v]] for v in range(self.n_par)); W = LD.parent_weight(self.M_par, z_tuple) / self.M_par.scalar; G = LD.upper_weight(self.M_par, self.Cz, c) / self.M_par.scalar
        d = F(1); r = F(1)
        for v in range(self.n_par): d *= self.Cz.d[v][z_tuple[v]]; r *= LD.r_prob(self.rows, v, c[v], z_tuple[v])
        return dict(c=c, W=W, G_U=G, d=d, r=r)
