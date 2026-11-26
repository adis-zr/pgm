"""Unified persistent planner with first-class PAC actions (DENSE_GENERIC_PAC_INTEGRATION_1, brief CLAUDE_DENSE_GENERIC_PAC_INTEGRATION.md 24 Nov 2026, sections 2-6). v0.5.
Builds on unified_planner.Planner v0.4.1 (deterministic representations identity / exact quotient / approximate quotient, R1 cost blocks, guarded feature pass, snapshot-derived status) and
pac_actions (the accepted v2.13.2 engine's structural routes and its PAC computation as resumable streams; the lifted upper-envelope proposal).
ONE request: immutable original binding + absolute request clock (process start); the original singleton inventory is frozen before any refusal; the accepted structural routes run first on the
ORIGINAL model with their checked precedence (signed > layered > ancestral; support closure before the partition); then the deterministic representations and up to THREE statistical streams
compete: s = 1 original / effective target (accepted block + mini-bucket PAC on the closure-reduced model), s = 2 a nonidentity exact quotient parent (PAC on the quotient, exact decoder
responses), s = 3 the lifted coarse proposal (--lifted; FULL arm). Stream s receives delta_s = delta / 2^s before its first draw and divides it over its frozen response inventory; identical
semantic streams alias; a stream's proposal / cap / response map / law are fixed once sampling starts; nothing is refunded. Deterministic rows consume no risk.
Policy (section 6, constants frozen here): (1) cheap deterministic opportunities and the accepted dependencies are kept; a ready deterministic continuation forecast to complete within W is
protected; (2) ONE cumulative exploration account E = min(W/4, T_inc/4) (ready affordable deterministic completion) else W/4, set at the first substantive route decision, never replenished,
charged with the ACTUAL time of every optional action (discovery, unknown-quality solves, refinement, alternative-stream preparation and probes); (3) with no affordable deterministic
completion the primary PAC stream (exact parent if a nonaliased exact quotient exists, else the effective target) is prepared under the accepted construction window (cdead = start + 0.5 x
budget) capped by the work cutoff -- a large identity forecast never makes PAC ineligible; (4) a ready stream advances in committed batches in slices of min(0.5 s, W/16), a batch in flight
is retained as pending work (same draws) or abandoned WITH its stream; an admitted alternative stream is probed once (one committed batch + one check) within E; (5) forecasts: deterministic
T from R1; statistical t_active x max(0, (w / 2 eps)^2 - 1) + check + final tail, only with >= 2 checkpoints and a positive witness, else UNKNOWN (a heuristic, recorded as such);
(6) after E is exhausted the incumbent with the best usable forecast runs; all statistical forecasts unknown -> the primary ready stream; reconsideration only at completed action / batch
boundaries; an incumbent with no usable alternative keeps the remaining work allowance; (7) stop as soon as the complete validated original snapshot meets the contract; termination
reason separate from the functional status. Publication: every route goes through the SAME epsilon-safe publisher (row box per variable, width <= 2 eps, J-box points, radius <= eps);
PAC rows are labelled PAC_EB; a deterministic enclosure that alone meets the width is published as DETERMINISTIC; an empty deterministic / PAC intersection is a recorded certificate conflict
(the variable is withheld, the evidence retained). Z: deterministic enclosure when available; the stream normalizer interval stays DIAGNOSTIC.
usage: unified_pac_planner.py --input M.uai --output R.json --budget 19.5 --admission-stop 19.0 --epsilon 1/200 --delta 1/1000000 --seed 1 [--lifted] [--no-pac]"""
import sys, os, json, time, math, argparse, resource
from fractions import Fraction as F
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import unified_planner as UP
from unified_planner import tnow, Clock, Budget, Refused, Defect, CE, CM, T_PROCESS_START
import pac_actions as PA
import integrated as IG
import joint_stream as JS
import joint_proposal as JP
VERSION = 'unified-pac-planner v0.9 (DGP5 25 Nov 2026: six DGP4-review repairs (bounded packing diagnostics + guarded comparisons + admission / polls of closure / packing / checker / adapter / fingerprint; exact-once checker inventory + bucket partition + closure / packing inventories; references dropped before charge release; fingerprint before the final readiness poll; ONE absolute optional allowance end that never reopens; strengthened D37 / D38 / D39 / D41); --joint seed|joint|cap_only|moment_only = the direct conditional proposal (joint_stream.JointStream: checked SUM / MAX seed with D = 2^40 dyadic conditionals, 1,024-draw pilot committed to ONE Certificate, <= 2 bounded MAX / SUM coefficient updates under the law\'s own checked cap / moment witnesses with the payback rule; offered in the optional slot instead of a not-yet-created RMAX stream when >= 8 s of work remain and shared admission passes; allowance min(E_remaining, 0.2 x work allowance, 4 s) with one absolute end) | v0.8 (DGP4 25 Nov 2026: R1 sorted-scope singleton tables; R2 owned construction charges released on every failure (grouped tables, decoder rows, RMAX); R3 action / phase sums before the authoritative sample; --envelope RMAX = residual MAX compilation on W_0 / r with the actual dyadic decoder, bound kind target_over_actual_decoder, production profile V 4096 / fan-in 16 / 128-bit, one midpoint allowance policy) | v0.7 (DGP3 25 Nov 2026: RF1 no variable-sized finalization work after the authoritative sample; RF2 deadline-aware admitted sampler / fine-table / grouped-table preparation with READY after a poll; RF3 cap metadata in W_int units 2^(logU_capf + E_U); --envelope G1|G2|G3 grouped-factor upper envelope for the lifted stream (lemma G); budget_obj on every stream) over v0.6 (DGP2 25 Nov 2026: F1 consumed widening incl. 5u|E_tot| + constant terms; F2 exact normalizer scale to the original on every stream exit; F3 finalization before the authoritative sample with expiry suppression + serialization guard; F4 valid confidence endpoints retained beyond the epsilon mask, decoded / intersected / tested on original coordinates; F5 charged optional stages cut at the allowance; compact 128-bit kappa enclosure, K_hi in the cap; lift-only check through the scoped compact ratio-product mode) over v0.5.1 (2026-11-25 post-freeze repair: streams publish their deterministically recovered EXACT rows (constant blocks, factorless) with the witness; the lifted cap constant in the log domain (no float of a huge rational); numeric exceptions and certificate defects inside a stream close THAT stream typed and recorded, never the request; a fully published stream is not advanced) over v0.5 (2026-11-24, DENSE_GENERIC_PAC_INTEGRATION_1: accepted structural routes + deterministic representations + up to three statistical streams under one cumulative exploration account; lifted upper-envelope proposal optional)'
SLICE_S = 0.5; SLICE_FRAC = 16; MAX_STREAMS = 3; EXPLORATION_FRAC = 4; CONSTRUCT_SHARE = 0.5; FINAL_RESERVE_S = CM.FINALIZE_RESERVE_S
JOINT_OFFER_MIN_WORK_S = JP.PROFILE_PRODUCTION['offer_min_work_s']; JOINT_ALLOWANCE_FRAC = JP.PROFILE_PRODUCTION['allowance_frac']; JOINT_ALLOWANCE_MAX_S = JP.PROFILE_PRODUCTION['allowance_max_s']        # DGP5 brief section 3 (frozen)
PAC_OPTS = dict(table_cap=1 << 18, enum_cap=1 << 16, mb_cap=1 << 24, batch=1024, schedule='targeted', crosscheck=True, exact_route=True)        # the accepted baseline settings (run_paired.FROZEN)


class UPlanner(UP.Planner):
    def __init__(self, model, binding, budget_s, eps=UP.EPS_DEFAULT, delta=F(1, 10 ** 6), admission_stop_s=19.0, t_start=None, seed=1, pac=True, lifted=False, sched='P1', rates='R1', force_stream=None, envelope='G1', joint=None):
        super().__init__(model, budget_s, eps=eps, admission_stop_s=admission_stop_s, t_start=t_start, policy='unified', sched=sched, rates=rates); self.force_stream = force_stream; self.envelope = envelope; self.joint = joint; self.joint_refused = None
        self.delta = delta; self.seed = seed; self.pac = pac; self.lifted = lifted; self.budget_s = budget_s; self.binding = binding
        self.req = PA.RequestState(model, binding, eps, delta); self.streams = []; self.primary = None; self.E = None; self.E_used = 0.0; self.first_decided = False; self.conflicts = []; self.checkpoints = []; self.pac_rows_orig = {}; self.lift_cands = []; self.lift_discovery_tried = False; self.fast_bits_refused = False
        self.out.update(version=VERSION, delta=str(delta), seed=seed, pac=pac, lifted=lifted, joint=joint, streams=[], risk_ledger=[], checkpoints=self.checkpoints, conflicts=self.conflicts); self.out['mechanism']['structural'] = self.req.mech
        self.cdead = self.t_start + min(budget_s, CONSTRUCT_SHARE * budget_s)
    # ---- risk
    def stream_key(self, kind, **kw):
        """semantic identity of a statistical stream: kind + target model (cards, evidence, every scope + exact value) + response inventory (+ lifted: class map and decoder)"""
        import hashlib; h = hashlib.sha256(kind.encode())
        if kind == 'lifted': M_par = kw['M_par']; h.update(self.envelope.encode()); h.update(json.dumps([list(M_par.cards), [[list(sc), [str(x) for x in v]] for sc, v in M_par.factors], [[str(x) for x in ps] for ps in M_par.psi], [list(c) for c in kw['classes']], [[str(x) for x in row] for row in kw['Cz'].d]]).encode())
        elif kind == 'joint': M_par = kw['M_par']; h.update(str(self.joint).encode()); h.update(json.dumps([list(M_par.cards), [[list(sc), [str(x) for x in v]] for sc, v in M_par.factors], [[str(x) for x in ps] for ps in M_par.psi], len(kw['par_stages'])]).encode())
        else: m = kw['model']; h.update(json.dumps([list(m['cards']), sorted(m.get('evidence', {}).items()), [[list(f['scope']), [str(x) for x in f['values']]] for f in m['factors']], list(kw['queries'])]).encode())
        return h.hexdigest()
    def new_stream(self, kind, **kw):
        key = self.stream_key(kind, **kw); same = next((S for S in self.streams if getattr(S, 'semantic_key', None) == key), None)
        if same is not None: self.log_action(action='alias_stream', stream=same.label, requested=kw.get('label'), note='identical semantic stream: no restart, no new risk'); return same
        s = len(self.streams) + 1
        if self.force_stream: s = {'original': 1, 'exact_parent': 1, 'lifted': 2, 'joint': 2}[kind]                      # the joint stream takes the OPTIONAL role's risk (delta / 4), never fresh risk                                # forced-stream diagnostic: the PLANNER-ROLE risk index (original / exact parent = stream 1 -> delta / 2; lifted = stream 2 -> delta / 4), never a free full delta
        if s > MAX_STREAMS: raise Refused('STREAMS', 'the declared maximum of %d statistical streams is reached' % MAX_STREAMS)
        delta_s = self.delta / 2 ** s; seed = np.random.SeedSequence([int(self.seed), s]).generate_state(1)[0]
        if kind == 'lifted': S = PA.LiftedStream(s, kw['M_fine'], kw['M_par'], kw['par_stages'], kw['classes'], kw['Cz'], int(seed), self.eps, delta_s, dict(PAC_OPTS, other_retained_bytes=self.retained_bytes(), budget_obj=self.budget), label=kw.get('label'), scale_to_original=kw.get('scale_to_original'), envelope=self.envelope)
        elif kind == 'joint': S = JS.JointStream(s, kw['M_fine'], kw['M_par'], kw['par_stages'], int(seed), self.eps, delta_s, dict(PAC_OPTS, other_retained_bytes=self.retained_bytes(), budget_obj=self.budget), label=kw.get('label'), scale_to_original=kw.get('scale_to_original'), mode=self.joint, profile=JP.PROFILE_PRODUCTION)
        else: S = PA.Stream(s, kind, kw['model'], kw['queries'], int(seed), self.eps, delta_s, dict(PAC_OPTS, other_retained_bytes=self.retained_bytes(), budget_obj=self.budget), label=kw.get('label'), scale_to_original=kw.get('scale_to_original', F(1)))
        S.decode_rows = kw.get('decode'); S.semantic_key = key; self.streams.append(S); self.out['risk_ledger'].append(dict(stream=s, kind=kind, label=S.label, delta_s=str(delta_s), created_t_s=round(tnow() - self.t_start, 4), seed=int(seed))); self.log_action(action='create_stream', stream=s, kind=kind, label=S.label, delta_s=str(delta_s)); return S
    def retained_bytes(self): return self.budget.live + sum(S.retained_bytes for S in self.streams)
    # ---- the three stream constructors
    def make_primary(self):
        ex = next((c for c in self.cands if c.kind == 'exact' and not c.alias_of), None)
        if ex is not None:
            M1 = ex.M1; classes1, Cz1 = ex.stages[0]; model = PA.canon_to_model(M1); queries = [(v, c) for v in range(len(M1.cards)) for c in range(M1.cards[v])]; M = self.M
            def decode(rows_q, S=None):                                                        # quotient coordinate (v, c) -> original (orig_of[v], a) rows for every a in class c: [d L, d H], exact decoder value d = Cz.d[v][a]
                qix = {q: j for j, q in enumerate(queries)}; outr = {}
                for v in range(len(M.cards)):
                    for a in range(M.cards[v]):
                        c = classes1[v][a]; j = qix[(v, c)]
                        if j in rows_q: L, H = rows_q[j]; d = Cz1.d[v][a]; outr[(M.orig_of[v], a)] = (d * L, d * H)
                return outr
            return self.new_stream('exact_parent', model=model, queries=queries, decode=decode, label='pac(exact_quotient)', scale_to_original=M1.scalar * M.scalar)      # F2: the quotient parent's scalar (1 by stage_model) and the canonical scalar (absorbed nullary / fixed / factorless mass)
        st = self.req; model = st.model; queries = st.queries
        def decode(rows_q, S=None):
            ans_eff = {j: dict(lo=L, hi=H, point=(L + H) / 2, guarantee='PAC_EB') for j, (L, H) in rows_q.items()}; ans_o, failed_o = st.decode_effective(ans_eff, [], True); outr = {}
            for j, r in ans_o.items(): x, a = st.queries_orig[j]; outr[(x, a)] = (r['lo'], r['hi'])
            return outr
        return self.new_stream('original', model=model, queries=queries, decode=decode, label='pac(original%s)' % ('/closure-reduced' if st.closure is not None else ''), scale_to_original=(st.closure['scalar'] if st.closure is not None else F(1)))     # F2: the accepted closure scalar (integrated.finish_ multiplies Z by it)
    def discover_fast_lift_only(self, parent, clock):
        """an approximate stage for LIFTING ONLY when the deterministic FAST discovery refused BITS on the diagnostic ratio product R = prod_f max U / L (the one-solve bound's constant, unused by the lifted
        proposal): the SAME proposer (slice profiles, farthest split, unit scales) and the SAME independent checker (coarse_envelope.check_candidate) with every entrywise quantity (u, A, d, L, U, Rf, gaps) under
        ORDINARY admission and ONLY the global ratio product formed as a compact 128-bit outward enclosure (ratio_product='compact'; DGP2). The candidate is kept OUT of self.cands (never a deterministic solve)."""
        live0 = self.budget.live; M1 = parent.M1
        try:
            prof, why = CE.slice_profiles(M1, clock, self.budget)
            if prof is None: raise Refused('PROPOSER', why)
            self.budget.charge(sum(c * c * 8 for c in M1.cards), 'pairwise distances (lift-only discovery)')
            classes2 = [CE.canonical_classes(CE.farthest_split(prof[v], list(range(M1.cards[v])), clock), M1.cards[v]) if M1.cards[v] > 1 else [0] for v in range(len(M1.cards))]
            Cz = CE.check_candidate(M1, classes2, CE.unit_scales(M1), clock, self.budget, ratio_product='compact')                   # the SAME checker under ORDINARY admission for every entrywise quantity; only the unused GLOBAL ratio product is compactly bounded (never the exact 4,096-bit-capped product, never a global cap change)
            worst = max([UP.bits(x) for row in Cz.A for x in row] + [UP.bits(x) for row in Cz.d for x in row] + [UP.bits(x) for row in Cz.u for x in row] + [UP.bits(x) for tab in Cz.U for x in tab] + [UP.bits(x) for tab in Cz.L for x in tab] + [0])
            if worst > CE.BIT_CAP: raise Refused('BITS', 'lift-only discovery: a consumed entrywise quantity needs %d > %d bits' % (worst, CE.BIT_CAP))      # every CONSUMED quantity must itself fit the ordinary cap (the checked_* operand guards bound operand growth, this bounds the stored results)
            R_bits = None; Cz.R = None
            c = UP.Cand('approx', parent); c.Cz = Cz; c.classes = classes2; c.scales = CE.unit_scales(M1); c.prof = prof; c.M1 = M1; c.stages = list(parent.stages) + [(classes2, Cz)]; c.cards = list(Cz.ccards); c.scopes = [sc for sc, _ in M1.factors]; c.constructions = parent.constructions + 1
            c.charged = self.budget.live - live0; c.name = 'approx_lift_only(%s)' % parent.name; c.owns = ['Cz', 'classes', 'prof', 'pairwise_distances']; c.shares = dict(M1=parent.name); c.max_bits = UP.cz_bits(Cz); c.lift_only = True; c.R_bits_discarded = R_bits; c.R_compact_log2_hi = (Cz.R_compact.log2_hi() if Cz.R_compact is not None else None); c.exact = Cz.exact; c.promising = False; c.R = None; c.mixed = Cz.mixed
            if c.charged < 0: raise Defect('negative construction charge (lift-only discovery)')
            return c
        except Refused: self.budget.release(max(0, self.budget.live - live0)); raise
    def make_lifted(self, approx):
        par = approx.parent; M_par = self.M if par.kind == 'identity' else par.M1; par_stages = [] if par.kind == 'identity' else par.stages; classes, Cz = approx.stages[-1]; M = self.M
        def decode(rows_q, S):
            outr = {}
            for j, (L, H) in rows_q.items(): v, a = S.queries[j]; outr[(M.orig_of[v], a)] = (L, H)
            return outr
        return self.new_stream('lifted', M_fine=M, M_par=M_par, par_stages=par_stages, classes=classes, Cz=Cz, decode=decode, label='lifted%s(%s)' % ('' if self.envelope == 'G1' else '_' + self.envelope, approx.name), scale_to_original=M_par.scalar * (M.scalar if par.kind != 'identity' else F(1)))
    def joint_parent(self):
        """the already available proper exact-quotient parent (checked response maps) when present, else identity (never a new discovery for this branch)"""
        return next((c for c in self.cands if c.kind == 'exact' and not c.alias_of), None) or next((c for c in self.cands if c.kind == 'identity'), None)
    def joint_admitted(self):
        """shared admission of the direct branch BEFORE creation: a seed-storage estimate (source tables + one family per variable at the seed volume + counts) must fit the constructor account and the process headroom"""
        par = self.joint_parent()
        if par is None: return False, 'no parent'
        M_par = par.M1; n = len(M_par.cards); est = JP.ENTRY_BYTES * (sum(M_par.cards) + sum(math.prod(M_par.cards[v] for v in sc) for sc, _ in M_par.factors)) + n * (JP.ENTRY_BYTES + JP.COUNT_BYTES) * JP.PROFILE_PRODUCTION['V_seed'] + (1 << 20)
        if self.budget.live + est > self.budget.cap: return False, 'constructor account: %d live + %d estimate > %d' % (self.budget.live, est, self.budget.cap)
        if est > self.headroom(): return False, 'process headroom %d < %d' % (self.headroom(), est)
        return True, dict(estimate_bytes=est, parent=par.name)
    def joint_allowance(self):
        """min(E_remaining, 0.20 x the initial request work allowance, 4 s) -- ONE absolute end set at the stream's first entry"""
        E_rem = max(0.0, (self.E or 0.0) - self.E_used); return min(E_rem, JOINT_ALLOWANCE_FRAC * (self.adm - self.t_start), JOINT_ALLOWANCE_MAX_S)
    def make_joint(self):
        par = self.joint_parent(); M = self.M; M_par = M if par.kind == 'identity' else par.M1; par_stages = [] if par.kind == 'identity' else par.stages
        def decode(rows_q, S):
            outr = {}
            for j, (L, H) in rows_q.items(): v, a = S.queries[j]; outr[(M.orig_of[v], a)] = (L, H)
            return outr
        return self.new_stream('joint', M_fine=M, M_par=M_par, par_stages=par_stages, decode=decode, label='joint_%s(%s)' % (self.joint, par.name), scale_to_original=M_par.scalar * (M.scalar if par.kind != 'identity' else F(1)))
    # ---- forecasts
    def stream_forecast(self, S):
        """remaining seconds to complete S (heuristic; None = unknown): needs >= 2 checkpoints and a positive witness"""
        if not S.ready() or S.checkpoints < 2 or not S.witness: return None
        if S.all_published(): return 0.0
        w = S.max_unresolved_width(); t = S.t_sample + S.t_cert; e = float(self.eps); need = t * max(0.0, (w / (2 * e)) ** 2 - 1.0)
        chk = (S.measurements[-1]['seconds'] if S.measurements and S.measurements[-1]['kind'] in ('pac_check',) else 0.05); fin = max(FINAL_RESERVE_S, self.cm.predict('final', dict(J=len(self.inventory))) if self.cm else FINAL_RESERVE_S)
        return need + chk + fin
    # ---- decision
    def _decide_forced(self):
        """forced-stream diagnostic (DGP2 brief section 5): bypass ONLY the offer decision -- build the requested stream with the production construction code and advance it alone; deterministic incumbents are not run"""
        W = self.W(); rec = dict(W_s=round(W, 4), t_s=round(tnow() - self.t_start, 4), forced=self.force_stream)
        if not self.first_decided: self.first_decided = True; self.E = W / EXPLORATION_FRAC; self.out['mechanism']['exploration_account_s'] = self.E
        live = [S for S in self.streams if S.live()]
        if not live and not self.streams:
            if self.force_stream == 'original': rec.update(chosen='create_primary', why='forced original stream'); return dict(kind='create_primary', record=rec)
            if self.force_stream == 'joint': rec.update(chosen='create_joint(%s)' % self.joint, why='forced joint stream (offer / selection forced only; the same allowance and profile)'); return dict(kind='create_joint', deadline=self.adm, record=rec)
            ap = [c for c in self.cands + self.lift_cands if c.kind == 'approx' and not c.alias_of and c.Cz is not None and not c.Cz.exact and not c.Cz.zero_factor]
            if ap: rec.update(chosen='create_lifted(%s)' % ap[-1].name, why='forced lifted stream'); return dict(kind='create_lifted', approx=ap[-1], deadline=self.adm, record=rec)
            parent = next((c for c in self.cands if c.kind == 'identity'), None)
            if not any(a.get('action') == 'discover_fast' for a in self.out['actions']):
                opts = [a for a in self.optional_actions() if a['name'] == 'discover_fast']
                if opts: rec.update(chosen='discover_fast', why='forced lifted stream: deterministic FAST discovery first'); return dict(kind='optional', act=opts[0], deadline=self.adm, record=rec)
            if not self.lift_discovery_tried and parent is not None: rec.update(chosen='discover_fast_lift', why='forced lifted stream: lift-only discovery after the deterministic FAST discovery refused'); return dict(kind='discover_fast_lift', parent=parent, deadline=self.adm, record=rec)
            rec.update(chosen='finalize', why='forced lifted stream: no approximate stage could be built (recorded construction failure)'); return dict(kind='finalize', outcome='REFUSED', why=rec['why'], record=rec)
        S = self.streams[-1]
        if S.live() and not S.ready(): rec.update(chosen='prepare_stream', stream=S.label, why='forced stream preparation'); return dict(kind='prepare', stream=S, deadline=(min(self.adm, S.allowance_end) if S.kind == 'joint' and S.allowance_end else self.adm), record=rec)
        if S.kind == 'joint' and S.ready() and S.can_pilot(): rec.update(chosen='joint_pilot', stream=S.label, why='forced joint: the seed pilot (charged action)'); return dict(kind='joint_pilot', stream=S, record=rec)
        if S.kind == 'joint' and S.ready() and S.can_refine(): rec.update(chosen='joint_refine', stream=S.label, why='forced joint: a bounded update attempt (charged action)'); return dict(kind='joint_refine', stream=S, record=rec)
        if S.ready() and not S.all_published(): slice_s = min(SLICE_S, W / SLICE_FRAC); rec.update(chosen='advance_stream', stream=S.label, slice_s=round(slice_s, 4), why='forced stream advance'); return dict(kind='advance', stream=S, deadline=min(self.adm, tnow() + slice_s), record=rec)
        rows = self.snapshot(); pub = sum(1 for r in rows.values() if r is not None); rec.update(chosen='finalize', why='forced stream ended (%s)' % (S.closed_reason or S.stage)); return dict(kind='finalize', outcome=('PARTIAL' if pub else 'REFUSED'), why=rec['why'], record=rec)
    def _decide(self):
        if self.force_stream: return self._decide_forced()
        W = self.W(); ready = self.ready_exact_or_promising(); rec = dict(W_s=round(W, 4), t_s=round(tnow() - self.t_start, 4)); scored = []
        for c, side in ready:
            T, parts = self.T_solve(c, 0 if side == 'lower' else 1); scored.append(dict(cand=c, side=side, T=T, parts=parts, admitted=self.admitted(c), order=(c.constructions, {'identity': 0, 'exact': 1, 'approx': 2}[c.kind], self.cands.index(c))))
        rec['ready'] = [dict(cand=s['cand'].name, side=s['side'], T_s=round(s['T'], 4), admitted=s['admitted'], fits_W=s['T'] <= W) for s in scored]
        fit = [s for s in scored if s['admitted'] and s['T'] <= W]; b = min(fit, key=lambda s: (s['T'], s['order'])) if fit else None
        if not self.first_decided:
            self.first_decided = True; self.E = min(W / EXPLORATION_FRAC, b['T'] / EXPLORATION_FRAC) if b else W / EXPLORATION_FRAC; self.out['mechanism']['exploration_account_s'] = self.E; rec['exploration_account_set_s'] = round(self.E, 4)
        E_rem = max(0.0, self.E - self.E_used); rec['E_remaining_s'] = round(E_rem, 4)
        opts = self.optional_actions(); live = [S for S in self.streams if S.live()]; readyS = [S for S in live if S.ready()]
        fc = {S.sid: self.stream_forecast(S) for S in readyS}; rec['streams'] = [dict(sid=S.sid, label=S.label, stage=S.stage, forecast_s=(round(fc[S.sid], 3) if S.sid in fc and fc[S.sid] is not None else None), draws=S.draws, published=len(S.pub), witness=S.witness, pending=(S.pending is not None)) for S in live]
        rec['optional'] = [dict(name=a['name'], cand=(a['cand'].name if a['cand'] is not None else None), D_s=round(a['D'], 4), S_s=round(a['S'], 4), admitted=a.get('admitted', True)) for a in opts]
        # ---- branch A: an affordable deterministic incumbent (steps 1, 2): optional work only inside E and only if it fits under the incumbent
        if b is not None:
            Tb = b['T']; rec.update(b=b['cand'].name, b_side=b['side'], T_b_s=round(Tb, 4))
            elig = [a for a in opts if a.get('admitted', True) and a['D'] <= E_rem and a['D'] + a['S'] < Tb and a['D'] + a['S'] < W]
            if elig:
                a = min(elig, key=lambda x: (x['D'] + x['S'], x['name'])); rec.update(chosen=a['name'], chosen_cand=(a['cand'].name if a['cand'] is not None else None), allowance_s=round(E_rem, 4), why='optional action inside the exploration account under a protected affordable incumbent (steps 1-2)')
                return dict(kind='optional', act=a, deadline=min(self.adm, tnow() + E_rem), record=rec)
            usable = [S.label for S in readyS if fc.get(S.sid) is not None and fc[S.sid] <= W] + [s['cand'].name + ':' + s['side'] for s in scored if s is not b and s['admitted'] and s['T'] <= W]
            dl = min(self.adm, tnow() + 2 * Tb) if usable else self.adm
            rec.update(chosen='solve_' + b['side'], chosen_cand=b['cand'].name, action_deadline_s=round(dl - self.t_start, 4), usable_alternatives=usable[:4], why='execute the affordable deterministic incumbent (%s)' % ('2 T_b allowance, a usable alternative remains' if usable else 'no usable alternative: the remaining work allowance'))
            return dict(kind='solve', cand=b['cand'], side=b['side'], deadline=dl, record=rec)
        # ---- branch B: no affordable deterministic completion
        if self.pac and self.primary is None and len(self.streams) < MAX_STREAMS:
            ex_opt = next((a for a in opts if a['name'] == 'discover_exact' and a['D'] <= E_rem), None)                 # a cheap exact quotient first: it decides the primary stream's target (step 1: cheap deterministic opportunity)
            if ex_opt is not None: rec.update(chosen='discover_exact', allowance_s=round(E_rem, 4), why='cheap exact-quotient discovery before the primary PAC target is chosen (step 1)'); return dict(kind='optional', act=ex_opt, deadline=min(self.adm, tnow() + E_rem), record=rec)
            rec.update(chosen='create_primary', why='no affordable deterministic completion: prepare the primary PAC stream under the accepted construction window (step 3)'); return dict(kind='create_primary', record=rec)
        if self.primary is not None and self.primary.live() and not self.primary.ready():
            rec.update(chosen='prepare_primary', why='primary PAC preparation continues (stages atomic; yields between stages)'); return dict(kind='prepare', stream=self.primary, deadline=self.adm, record=rec)
        # alternatives inside E (step 4): lifted stream creation + one probe (FULL), FAST discovery that enables it, unknown-quality solves / refinement
        alt = []
        if E_rem > 0.01:
            for a in opts:
                if a.get('admitted', True) and a['D'] <= E_rem: alt.append(dict(kind='optional', act=a, D=a['D'] + a['S'], name=a['name']))
            joint_live = [S for S in self.streams if S.kind == 'joint']
            for S in joint_live:                                                                      # the explicit CHARGED actions of a ready joint stream (pilot, then <= 2 refinement attempts) inside the account
                if S.ready() and S.can_pilot(): alt.append(dict(kind='joint_pilot', stream=S, D=0.0, name='joint_pilot(%s)' % S.label))
                elif S.ready() and S.can_refine(): alt.append(dict(kind='joint_refine', stream=S, D=0.0, name='joint_refine(%s)' % S.label))
            offer_joint = False
            if self.joint and len(self.streams) < MAX_STREAMS and not any(S.kind in ('lifted', 'joint') for S in self.streams) and self.joint_refused is None:
                if W >= JOINT_OFFER_MIN_WORK_S:
                    ok, why = self.joint_admitted()
                    if ok: offer_joint = True; alt.append(dict(kind='create_joint', D=0.0, name='create_joint(%s)' % self.joint)); rec['joint_offer'] = dict(offered=True, admission=why, allowance_s=round(self.joint_allowance(), 4))
                    else: self.joint_refused = 'ADMISSION: %s' % why; rec['joint_offer'] = dict(offered=False, reason=self.joint_refused); self.log_action(action='joint_offer', status='NOT_OFFERED', reason=self.joint_refused)
                else: self.joint_refused = 'OFFER_THRESHOLD: %.3f s of work remain < %.1f s' % (W, JOINT_OFFER_MIN_WORK_S); rec['joint_offer'] = dict(offered=False, reason=self.joint_refused); self.log_action(action='joint_offer', status='NOT_OFFERED', reason=self.joint_refused)
            if (not offer_joint) and self.lifted and len(self.streams) < MAX_STREAMS and not any(S.kind in ('lifted', 'joint') for S in self.streams):       # the repaired old optional route (RMAX / G2) when the new offer does not apply; never both in one slot
                ap = [c for c in self.cands + self.lift_cands if c.kind == 'approx' and not c.alias_of and c.Cz is not None and not c.Cz.exact and not c.Cz.zero_factor]
                if ap: a0 = ap[-1]; alt.append(dict(kind='create_lifted', approx=a0, D=0.0, name='create_lifted(%s)' % a0.name))
                elif 'fast_discovery' in self.failed_global and self.fast_bits_refused and not self.lift_cands and not self.lift_discovery_tried:
                    parent = next((c for c in self.cands if c.kind == 'exact' and not c.alias_of), None) or next((c for c in self.cands if c.kind == 'identity'), None)
                    if parent is not None: alt.append(dict(kind='discover_fast_lift', parent=parent, D=0.0, name='discover_fast_lift(%s)' % parent.name))
            for S in readyS:
                if S is not self.primary and S.batches == 0: alt.append(dict(kind='probe', stream=S, D=0.0, name='probe(%s)' % S.label))
        if alt:
            a = min(alt, key=lambda x: (x['D'], x['name'])); q = E_rem if a['kind'] != 'probe' else min(E_rem, SLICE_S, W / SLICE_FRAC); rec.update(chosen=a['name'], allowance_s=round(q, 4), why='alternative inside the cumulative exploration account (step 4%s)' % ('; one probe slice' if a['kind'] == 'probe' else ''))
            if a['kind'] == 'optional': return dict(kind='optional', act=a['act'], deadline=min(self.adm, tnow() + q), record=rec)
            return dict(a, deadline=min(self.adm, tnow() + q), record=rec)
        # step 6: the incumbent with the best usable forecast; all unknown -> the primary ready stream; a deterministic bounded attempt only when no stream is live
        advS = [S for S in readyS if not S.all_published()]
        if advS:
            usable = [(fc[S.sid], S.sid, S) for S in advS if fc.get(S.sid) is not None and fc[S.sid] <= W]          # step 6: a USABLE forecast fits the remaining work time; a known forecast beyond W is not usable
            S = min(usable)[2] if usable else (self.primary if (self.primary in advS) else advS[0])
            slice_s = min(SLICE_S, W / SLICE_FRAC); rec.update(chosen='advance_stream', stream=S.label, slice_s=round(slice_s, 4), forecast_s=(round(fc[S.sid], 3) if fc.get(S.sid) is not None else None), why=('best usable statistical forecast' if usable else 'no usable statistical forecast: the primary ready stream continues (the incumbent keeps the remaining work allowance)'))
            return dict(kind='advance', stream=S, deadline=min(self.adm, tnow() + slice_s), record=rec)
        pend = [S for S in live if not S.ready()]
        if pend: S = pend[0]; rec.update(chosen='prepare_stream', stream=S.label, why='a created stream is still preparing'); return dict(kind='prepare', stream=S, deadline=self.adm, record=rec)
        untried = [s for s in scored if s['admitted']]
        if untried:
            b2 = min(untried, key=lambda s: (s['T'], s['order'])); rec.update(chosen='solve_' + b2['side'], chosen_cand=b2['cand'].name, why='no live stream: bounded attempt of the cheapest admitted deterministic solve on the remaining work allowance (step 6)')
            return dict(kind='solve', cand=b2['cand'], side=b2['side'], deadline=self.adm, record=rec)
        rows = self.snapshot(); pub = sum(1 for r in rows.values() if r is not None)
        rec.update(chosen='finalize', why='no admitted action remains' + (' (every live stream has published its whole inventory)' if readyS else '')); return dict(kind='finalize', outcome=('PARTIAL' if pub else 'REFUSED'), why=rec['why'], record=rec)
    # ---- execution
    def _perform(self, d):
        k = d['kind']; t0 = tnow(); rec = d['record']
        if k in ('solve',): return super()._perform(d)
        if k == 'optional':
            try: r = super()._perform(d)
            finally: self.E_used += tnow() - t0
            if d['act']['name'] == 'discover_fast' and self.out['actions'] and self.out['actions'][-1].get('action') == 'discover_fast' and self.out['actions'][-1].get('status') == 'REFUSED_BITS': self.fast_bits_refused = True
            return r
        if k == 'create_primary':
            try: self.primary = self.make_primary()
            except Refused as e: self.pac = False; self.log_action(action='create_primary', status='REFUSED_' + e.kind, reason=str(e.reason)[:160]); return None
            return self._prepare(self.primary, min(self.adm, d.get('deadline', self.adm)), charge=False)
        if k == 'prepare': return self._prepare(d['stream'], d['deadline'], charge=(d['stream'] is not self.primary))
        if k == 'create_lifted':
            try: S = self.make_lifted(d['approx'])
            except Refused as e: self.lifted = False; self.log_action(action='create_lifted', status='REFUSED_' + e.kind, reason=str(e.reason)[:160]); self.E_used += tnow() - t0; return None
            if self.force_stream == 'lifted': self.primary = S; return self._prepare(S, self.adm, charge=False)                          # forced diagnostic: the lifted stream IS the request's primary (uncharged, work cutoff)
            r = self._prepare(S, d['deadline'], charge=True)
            if r is None and S.ready() and tnow() < d['deadline']: return self._probe(S, min(d['deadline'], tnow() + min(SLICE_S, max(0.0, self.W()) / SLICE_FRAC)))        # the one probe is ONE slice inside the account
            return r
        if k == 'discover_fast_lift':
            self.lift_discovery_tried = True; aclock = Clock(d['deadline'], self.stats)
            try: c = self.discover_fast_lift_only(d['parent'], aclock); self.lift_cands.append(c); self.log_action(action='discover_fast_lift', parent=d['parent'].name, actual_s=tnow() - t0, status='READY_LIFT_ONLY', cards=c.cards, R_bits_discarded=c.R_bits_discarded, charged_bytes=c.charged)
            except Refused as e: self.log_action(action='discover_fast_lift', parent=d['parent'].name, actual_s=tnow() - t0, status='REFUSED_' + e.kind, reason=str(e.reason)[:160])
            self.E_used += tnow() - t0; return None
        if k == 'create_joint':
            try: S = self.make_joint()
            except Refused as e: self.joint_refused = 'CREATE_' + e.kind; self.log_action(action='create_joint', status='REFUSED_' + e.kind, reason=str(e.reason)[:160]); self.E_used += tnow() - t0; return None
            allow = (min(JOINT_ALLOWANCE_FRAC * (self.adm - self.t_start), JOINT_ALLOWANCE_MAX_S) if self.force_stream == 'joint' else self.joint_allowance()); until = tnow() + allow
            self.log_action(action='create_joint', stream=S.label, mode=self.joint, allowance_s=allow, absolute_allowance_end_offset_s=until - self.t_start, parent=S.label)
            if self.force_stream == 'joint': self.primary = S; return self._prepare(S, min(self.adm, until), charge=False)              # forced diagnostic: the joint stream IS the request's primary; the SAME allowance bounds its preparation
            return self._prepare(S, min(self.adm, until), charge=True)
        if k == 'joint_pilot':
            S = d['stream']; r = S.pilot_action(min(self.adm, S.allowance_end)); dt = tnow() - t0; self.E_used += dt
            self.log_action(action='joint_pilot', stream=S.label, actual_s=dt, result=r.get('status'), draws=r.get('draws'), batches=r.get('batches'), log2_Z_proxy_fit=r.get('log2_Z_proxy_fit'), d_seed_s_per_draw=r.get('d_seed_s_per_draw'), closed=S.closed_reason); self.record_checkpoint(); return self.try_finish()
        if k == 'joint_refine':
            S = d['stream']; r = S.refine_action(min(self.adm, S.allowance_end), self.adm); dt = tnow() - t0; self.E_used += dt
            self.log_action(action='joint_refine', stream=S.label, actual_s=dt, status=r.get('status'), promoted=r.get('promoted'), winner=r.get('winner'), family=r.get('family'), payback=r.get('payback'), kind=r.get('kind'), why=r.get('why'), committed_epoch=r.get('committed_epoch')); return None
        if k == 'probe': return self._probe(d['stream'], d['deadline'])
        if k == 'advance': return self._advance(d['stream'], d['deadline'])
        raise Defect('unknown decision kind %s' % k)
    def _prepare(self, S, deadline, charge):
        """F5: a CHARGED (optional) stream's stages run against the allowance end `deadline` as their hard cutoff (a Deadline inside a stage closes the stream typed), so an optional action can never consume the
        primary's remaining time first and debit the account afterwards; the primary (uncharged) stream keeps the work cutoff"""
        t0 = tnow(); hard = min(self.adm, deadline) if (charge or S.kind == 'joint') else self.adm; r = S.prepare(hard, cdead=min(self.cdead, hard) if charge else self.cdead, until=deadline); dt = tnow() - t0
        if charge: self.E_used += dt
        self.log_action(action='prepare_stream', stream=S.label, result=r, actual_s=dt, stage=S.stage, closed=S.closed_reason, retained_bytes=S.retained_bytes)
        if S.stage == 'COMPLETE': return self._stream_terminal(S)
        return None
    def _stream_terminal(self, S):
        """a stream that completed deterministically (exact contraction / enumeration / exact reverse route) or proved zero mass"""
        term = S.mech.get('terminal')
        if term in ('ZERO_EVIDENCE', 'ZERO_MASS_PROVED_BY_UPPER_MODEL'):
            if S.kind == 'lifted' and term == 'ZERO_EVIDENCE': return None                         # the fine integerization is on the parent: an exact zero there IS zero original mass, but the planner's canonical pass already decided zero_mass; keep typed
            self.out['mechanism']['positive_mass_witness'] = False; self.out['Z_enclosure'] = dict(lo='0', hi='0', positive=False); raise Refused('ZERO_MASS', 'stream %s: %s' % (S.label, term))
        if S.deterministic_rows is not None and S.witness:
            rows_q = {j: (r['lo'], r['hi']) for j, r in S.deterministic_rows.items()}; orig = S.decode_rows(rows_q, S) if S.decode_rows else {}
            acc = {}
            for (x, a), (L, H) in orig.items():
                v = self.orig_to_canon.get(x)
                if v is None: continue
                acc[(v, a)] = (L, H)
            if acc: self.retained = CE.intersect(self.retained, acc) if self.retained else acc
            self.out['mechanism']['positive_mass_witness'] = True
            if S.Z is not None: Zo = S.Z_original(); self.out['Z_enclosure'] = dict(lo=str(Zo), hi=str(Zo), positive=Zo > 0, source=S.label, Z_effective=str(S.Z), scale_to_original=str(S.scale_to_original), exact=True)      # F2: restored exactly once
            self.log_action(action='stream_deterministic_rows', stream=S.label, terminal=term, rows=len(acc))
            return self.try_finish()
        return None
    def _probe(self, S, deadline):
        """one probe inside the exploration account: committed batches for the allowance with a certificate check after the first and after the last (two checkpoints -> a forecast can exist)"""
        t0 = tnow(); r = S.batch(deadline, self.adm); n = (r == 'COMMITTED')
        if n: S.check()
        while tnow() < deadline and S.ready() and not S.all_published():
            r = S.batch(deadline, self.adm)
            if r != 'COMMITTED': break
            n += 1
        if n >= 2: S.check()
        self.E_used += tnow() - t0; self.log_action(action='probe_stream', stream=S.label, result=r, batches=n, actual_s=tnow() - t0, draws=S.draws, witness=S.witness, max_remaining_width=S.max_unresolved_width()); self.record_checkpoint()
        return self.try_finish()
    def _advance(self, S, deadline):
        t0 = tnow(); n = 0; r = None
        while tnow() < deadline and S.ready() and not S.all_published():
            r = S.batch(deadline, self.adm); n += (r == 'COMMITTED')
            if r != 'COMMITTED': break
        if S.ready() and n: S.check()
        self.log_action(action='advance_stream', stream=S.label, batches=n, last=r, actual_s=tnow() - t0, draws=S.draws, published=len(S.pub), Kq=getattr(S, 'Kq', None), witness=S.witness, max_remaining_width=S.max_unresolved_width(), pending=(S.pending is not None), closed=S.closed_reason); self.record_checkpoint()
        if S.witness: self.out['mechanism']['positive_mass_witness'] = True
        return self.try_finish()
    # ---- snapshot / publication
    def pac_enclosures(self):
        """{(orig var, state): [(lo, hi, stream label), ...]} from every stream's certified coordinates"""
        acc = {}
        for S in self.streams:
            rows_q = S.pac_rows()
            if not rows_q or S.decode_rows is None: continue
            for q, (L, H) in S.decode_rows(rows_q, S).items(): acc.setdefault(q, []).append((L, H, S.label))
        return acc
    def stream_exact_enclosures(self):
        """{(orig var, state): (lo, hi)} of the EXACT rows recovered deterministically inside streams (constant blocks, factorless), decoded to original coordinates; zero risk"""
        acc = {}
        for S in self.streams:
            rows_q = S.exact_rows() if hasattr(S, 'exact_rows') else {}
            if not rows_q or S.decode_rows is None: continue
            for q, (L, H) in S.decode_rows(rows_q, S).items():
                if q in acc and acc[q] != (L, H): raise Defect('two streams recover different exact rows for %s' % (q,))
                acc[q] = (L, H)
        return acc
    def snapshot(self):
        """the combined original snapshot through the one epsilon-safe publisher: per variable the row box of deterministic enclosures (orig coordinates; planner-retained + streams' exact rows) intersected with PAC enclosures"""
        M = self.M; det = {}
        for (v, a), (lo, hi) in self.retained.items(): det[(M.orig_of[v], a)] = (lo, hi)
        for q, (L, H) in self.stream_exact_enclosures().items():
            if q in det:
                nlo, nhi = max(det[q][0], L), min(det[q][1], H)
                if nlo > nhi: raise Defect('deterministic rows disagree at %s' % (q,))
                det[q] = (nlo, nhi)
            else: det[q] = (L, H)
        pac = self.pac_enclosures(); rows = {}
        by_var = {}
        for (x, a) in list(det) + list(pac): by_var.setdefault(x, set()).add(a)
        for x, states in by_var.items():
            card = self.cards_in[x]; box = []; labels = []; ok = True
            for a in range(card):
                d = det.get((x, a)); ps = pac.get((x, a), [])
                lo, hi = (d if d else (F(0), F(1))); det_ok = bool(d) and hi - lo <= 2 * self.eps; lab = ('EXACT' if lo == hi else 'DETERMINISTIC') if det_ok else None
                for (L, H, s) in ps:                                                           # every PAC enclosure is intersected (a disjoint pair is a recorded certificate conflict even when the deterministic row alone would suffice)
                    nlo, nhi = max(lo, L), min(hi, H)
                    if nlo > nhi: self.conflicts.append(dict(var=x, state=a, deterministic=(str(lo), str(hi)) if d else None, pac=(str(L), str(H), s), t_s=round(tnow() - self.t_start, 4))); ok = False; break
                    if not det_ok: lo, hi = nlo, nhi; lab = 'PAC_EB'
                if not ok: break
                box.append((lo, hi)); labels.append(lab if lab else 'NONE')
            if not ok: rows.update({(x, a): None for a in range(card)}); continue
            if any(l == 'NONE' for l in labels) or any(hi - lo > 2 * self.eps for lo, hi in box): rows.update({(x, a): None for a in range(card)}); continue
            s_lo = sum(b[0] for b in box); s_hi = sum(b[1] for b in box)
            if not (s_lo <= 1 <= s_hi):
                if all(l in ('EXACT', 'DETERMINISTIC') for l in labels): raise Defect('deterministic row box of variable %d misses the simplex' % x)
                self.conflicts.append(dict(var=x, simplex=(str(s_lo), str(s_hi)), note='PAC-involved row box misses the simplex', t_s=round(tnow() - self.t_start, 4))); rows.update({(x, a): None for a in range(card)}); continue
            pts, policy = CE.epsilon_safe_points([(lo, hi, lab) for (lo, hi), lab in zip(box, labels)], self.eps)
            for a in range(card):
                lo, hi = box[a]; p = pts[a]
                if not (lo <= p <= hi and max(p - lo, hi - p) <= self.eps): rows.update({(x, aa): None for aa in range(card)}); break
                rows[(x, a)] = dict(lo=lo, hi=hi, point=p, guarantee=labels[a])
        return rows
    def record_checkpoint(self):
        enc = self.all_enclosures(); ws = [float(hi - lo) for (lo, hi) in enc.values()]; cov = sum(1 for w in ws if w <= 2 * float(self.eps))
        self.checkpoints.append(dict(t_s=round(tnow() - self.t_start, 4), covered=cov, K=len(self.inventory), worst_radius=(max(ws) / 2 if ws else None), median_radius=(float(np.median(ws)) / 2 if ws else None), p90_radius=(float(np.percentile(ws, 90)) / 2 if ws else None)))
    def all_enclosures(self):
        """every original coordinate -> its current valid enclosure (deterministic / PAC intersection), [0, 1] if unresolved; fixed rows exact"""
        M = self.M; enc = {}
        det = {(M.orig_of[v], a): (lo, hi) for (v, a), (lo, hi) in self.retained.items()} if M is not None else {}
        for q, (L, H) in self.stream_exact_enclosures().items(): det[q] = (max(det[q][0], L), min(det[q][1], H)) if q in det else (L, H)
        pac = self.pac_enclosures()
        for (x, a) in self.inventory:
            if M is not None and (x, a) in M.fixed_rows and M.fixed_rows[(x, a)][0] is not None: val = M.fixed_rows[(x, a)][0]; enc[(x, a)] = (val, val); continue
            lo, hi = det.get((x, a), (F(0), F(1)))
            for (L, H, s) in pac.get((x, a), []):
                if max(lo, L) <= min(hi, H): lo, hi = max(lo, L), min(hi, H)
            enc[(x, a)] = (lo, hi)
        return enc
    def try_finish(self):
        rows = self.snapshot(); pos = self.out['mechanism'].get('positive_mass_witness')
        if not pos: return None
        M = self.M; need = [(x, a) for (x, a) in self.inventory if not ((x, a) in M.fixed_rows and M.fixed_rows[(x, a)][0] is not None)]
        if all(rows.get(q) is not None for q in need): self.complete = True; return rows
        return None
    # ---- run / fin
    def run(self):
        out = self.out; mech = out['mechanism']; t0 = tnow()
        try:
            self.hclock.poll('at the planner entry'); self.clock.poll('at the planner entry (admission)')
            status, rows_o, info = PA.structural_routes(self.req, self.adm); out['phases_s']['structural_routes'] = tnow() - t0; mech['structural_info'] = {k: v for k, v in info.items() if k != 'Z_enclosure'}
            if status == 'COMPLETE':
                mech['positive_mass_witness'] = True; mech['route'] = info.get('route'); out['Z_enclosure'] = info.get('Z_enclosure') or (dict(lo=info['Z'], hi=info['Z'], positive=True) if info.get('Z') else None); rows = {}
                for j, r in rows_o.items(): x, a = self.req.queries_orig[j]; rows[(x, a)] = dict(lo=r['lo'], hi=r['hi'], point=r['point'], guarantee=r['guarantee'])
                self.M = CE.canonicalize(self.model, self.hclock, self.budget) if False else _EmptyCanon(); self.t_mark = tnow(); return self.finish_ok(rows, 'accepted structural route %s completed the request' % info.get('route'))
            if status == 'ZERO_EVIDENCE': mech['positive_mass_witness'] = False; out['Z_enclosure'] = dict(lo='0', hi='0', positive=False); self.M = _EmptyCanon(); self.t_mark = tnow(); return self.fin('ZERO_EVIDENCE', {}, note='accepted structural route: zero evidence (%s)' % info.get('route'))
            if status == 'DEADLINE': mech['positive_mass_witness'] = None; self.M = _EmptyCanon(); self.t_mark = tnow(); return self.fin('DEADLINE', {}, note='work cutoff during the accepted structural routes (%s)' % info.get('phase'))
            if status == 'CERTIFICATE_DEFECT': mech['defect'] = info.get('error'); self.M = _EmptyCanon(); self.t_mark = tnow(); return self.fin('CERTIFICATE_DEFECT', {})
            t1 = tnow(); self.M = M = CE.canonicalize(self.model, self.clock, self.budget); out['phases_s']['canonicalize'] = tnow() - t1; self.canonical_charge = self.budget.live; self.orig_to_canon = {int(M.orig_of[v]): v for v in range(len(M.cards))}
            mech['canonical'] = dict(variables=len(M.cards), factors=len(M.factors), entries=sum(len(v) for _, v in M.factors), removed_fixed=len(M.fixed_rows), scalar_bits=UP.bits(M.scalar))
            t2 = tnow(); self.mf = CM.model_features(M, self.clock, self.budget); out['phases_s']['features'] = tnow() - t2; mech['features'] = dict(self.mf); self.t_mark = tnow()
            if M.zero_mass: mech['positive_mass_witness'] = False; out['Z_enclosure'] = dict(lo='0', hi='0', positive=False); return self.fin('ZERO_EVIDENCE', {}, note='a canonical scalar is exactly zero')
            if not M.cards: mech['positive_mass_witness'] = True; out['Z_enclosure'] = dict(lo=str(M.scalar), hi=str(M.scalar), positive=True); return self.finish_ok({}, 'no retained variables: exact scalar normalizer')
            t1 = tnow(); ident = self.make_identity(self.clock); self.cands.append(ident); out['phases_s']['price_identity'] = tnow() - t1
            Tid, parts = self.T_solve(ident); self.log_action(action='price', cand='identity', estimate_s=Tid, parts={k: round(v, 5) for k, v in parts.items()}, volume=ident.vol, forecast_bytes=ident.fbytes, actual_s=tnow() - t1, status='PRICED'); self.t_mark = tnow()
            while True:
                self.clock.poll('between actions'); decision = self.decide(); out['decisions'].append(decision['record'])
                if decision['kind'] == 'finalize': return self.fin(decision['outcome'], self.snapshot(), note=decision['why'])
                done = self.perform(decision)
                if done: return self.finish_ok(done, decision['record'].get('why', 'complete'))
        except Refused as e:
            if e.kind == 'ZERO_MASS': mech['positive_mass_witness'] = False; out['Z_enclosure'] = dict(lo='0', hi='0', positive=False); return self.fin('ZERO_EVIDENCE', {}, note=str(e.reason)[:200])
            mech['refusal'] = dict(kind=e.kind, reason=str(e.reason)[:300]); rows = {}
            if self.M is not None and not isinstance(self.M, _EmptyCanon) and tnow() < self.hard:
                try: rows = self.snapshot()
                except (Refused, Defect) as d: rows = {}; mech['late_publish'] = str(d)[:120]
            return self.fin('DEADLINE' if e.kind == 'DEADLINE' and not any(rows.values()) else ('DEADLINE_PARTIAL' if e.kind == 'DEADLINE' else ('PARTIAL' if any(rows.values()) else 'REFUSED')), rows)
        except Defect as e: mech['defect'] = str(e)[:300]; return self.fin('CERTIFICATE_DEFECT', {})
        except (ValueError, OverflowError, ZeroDivisionError) as e:
            import traceback; mech['refusal'] = dict(kind='INVALID_OR_NUMERIC', reason=str(e)[:300], traceback=traceback.format_exc()[-900:]); return self.fin('REFUSED', {})
    def fin(self, oc, rows, note=None):
        out = self.out; mech = out['mechanism']
        if self.M is None: self.M = _EmptyCanon()
        for S in self.streams:
            if S.pending is not None: S.mech['pending_batch_at_end'] = dict(draws_generated=int(S.pending['Sb'].shape[0]), blocks_done=S.pending['bi'])
        for S in self.streams:
            if hasattr(S, 'fingerprint'): S.mech['proposal_fingerprint_at_ready'] = S.fingerprint; S.mech['proposal_fingerprint_at_end'] = S.proposal_fingerprint(); S.mech['proposal_immutable'] = (S.fingerprint == S.mech['proposal_fingerprint_at_end'])
        defects = [dict(stream=S.label, defect=S.defect) for S in self.streams if getattr(S, 'defect', None)]
        if defects: mech['stream_certificate_defects'] = defects; mech['defect'] = (mech.get('defect') or '') + ' | stream defects: ' + '; '.join(d['stream'] + ': ' + d['defect'][:80] for d in defects)
        out['streams'] = [S.diagnostics() for S in self.streams]; mech['joint_offer'] = dict(mode=self.joint, refused=self.joint_refused, created=any(S.kind == 'joint' for S in self.streams)); mech.update(exploration_account_s=self.E, exploration_used_s=self.E_used, streams_created=len(self.streams), live_memory_named_bytes=dict(constructor_live=self.budget.live, streams_retained=sum(S.retained_bytes for S in self.streams)), lift_only_candidates=[dict(name=c.name, cards=c.cards, charged_bytes=c.charged, R_compact_log2_hi=getattr(c, 'R_compact_log2_hi', None), exact=c.exact, mixed=c.mixed) for c in self.lift_cands])
        # F3: ALL enclosure / radius / cost / diagnostic work happens here, BEFORE the authoritative final sample inside super().fin; afterwards only the already-built objects are attached, and only when the sample respected the hard deadline
        try: enc = self.all_enclosures() if not isinstance(self.M, _EmptyCanon) else {}
        except Exception as e: enc = {}; mech['enclosure_report_error'] = repr(e)[:120]
        enc_rows = [dict(var=x, state=a, lo=str(enc[(x, a)][0]), hi=str(enc[(x, a)][1])) for (x, a) in self.inventory if (x, a) in enc]
        ws = [float(enc[(x, a)][1] - enc[(x, a)][0]) / 2 for (x, a) in self.inventory if (x, a) in enc]; radius = dict(worst=(max(ws) if ws else None), median=(float(np.median(ws)) if ws else None), p90=(float(np.percentile(ws, 90)) if ws else None), covered_at_eps=sum(1 for w in ws if w <= float(self.eps)), K=len(self.inventory))
        cost = self.cost_breakdown(); ledger_identity = (self.budget.live == getattr(self, 'canonical_charge', 0) + sum(c.charged for c in self.cands) + sum(c.charged for c in self.lift_cands) + sum(getattr(S, 'rows', None).bytes if getattr(S, 'rows', None) is not None else 0 for S in self.streams) + sum(getattr(S, 'fine_bytes', 0) + getattr(S, 'grouped_bytes', 0) + getattr(S, 'rmax_bytes', 0) + getattr(S, 'joint_bytes', 0) for S in self.streams))   # RF1: the ledger sum is variable-sized -> before the sample; DGP3: the lifted stream's admitted fine / grouped tables are constructor-account charges
        res = super().fin(oc, rows, note=note); mech['constructor_live_ledger_identity'] = ledger_identity
        gs = self._fin_gs; res['guarantee'] = 'EXACT' if gs <= {'EXACT'} else ('DETERMINISTIC' if gs <= {'EXACT', 'DETERMINISTIC'} else ('PAC' if gs <= {'EXACT', 'DETERMINISTIC', 'PAC_EB'} else 'PARTIAL'))      # RF1: the guarantee set the parent collected DURING assembly (no traversal after the sample); constant-size work only from here on
        pub = res['published']
        if pub == len(res['answers']) and pub > 0 and res['hard_deadline_respected'] and res['guarantee'] in ('EXACT', 'DETERMINISTIC', 'PAC') and mech.get('positive_mass_witness'): res['outcome'] = 'COMPLETE'
        elif res['outcome'] == 'COMPLETE' and pub < len(res['answers']): res['outcome'] = 'PARTIAL'
        if res['hard_deadline_respected']: res['enclosures'] = enc_rows; res['radius_report'] = radius
        else: res['enclosures'] = []; res['radius_report'] = None; mech['suppressed_on_expiry'] = dict(enclosures=len(enc_rows), radius_report=True)
        res['cost_breakdown'] = cost; return res
    def cost_breakdown(self):
        ph = self.out['phases_s']; acts = self.out['actions']; b = dict(structural_routes=ph.get('structural_routes', 0.0), canonicalize=ph.get('canonicalize', 0.0), features=ph.get('features', 0.0), pricing=ph.get('pricing', 0.0) + ph.get('price_identity', 0.0), final_assembly=ph.get('final_assembly', 0.0), output=ph.get('output', 0.0))
        b['quotient_construction'] = sum(a.get('actual_s') or 0 for a in acts if a.get('action') in ('discover_exact', 'discover_fast', 'refine')); b['native_solves'] = sum(a.get('actual_s') or 0 for a in acts if str(a.get('action', '')).startswith('solve_'))
        for S in self.streams:
            for m in S.measurements:
                key = {'pac_stage': 'pac_preparation', 'lifted_stage': 'lifted_preparation', 'joint_stage': 'joint_preparation', 'pac_batch': 'sampling_target_evaluation', 'lifted_batch': 'sampling_target_evaluation', 'joint_batch': 'sampling_target_evaluation', 'joint_action': 'joint_actions', 'pac_check': 'confidence_checks'}[m['kind']]; b[key] = b.get(key, 0.0) + m['seconds']
            if S.kind != 'lifted':
                for k in ('contract', 'mb_construct', 'exact_route', 'executor_crosscheck', 'sampler_prep', 'enumerate'):
                    if k in S.ph: b['pac_' + k] = b.get('pac_' + k, 0.0) + S.ph[k]
        b['time_to_first_committed_batch_s'] = next((a['t_s'] for a in acts if a.get('action') in ('advance_stream', 'probe_stream', 'joint_pilot') and (a.get('batches') or a.get('result') == 'COMMITTED')), None)
        b['joint_mechanism'] = next(({k: S.diagnostics().get('joint', {}).get(k) for k in ('mode', 'current_epoch', 'epoch_switches', 'refinement_ended')} | dict(stage=S.stage, closed=S.closed_reason, draws=S.draws, published=len(S.pub), attempts=len(S.attempts), offered=True) for S in self.streams if S.kind == 'joint'), dict(offered=False, reason=self.joint_refused))
        return b


class _EmptyCanon:
    cards = []; fixed_rows = {}; orig_of = []; scalar = F(1); zero_mass = False; factors = []; psi = []


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--input', required=True); ap.add_argument('--output', required=True); ap.add_argument('--budget', type=float, default=19.5); ap.add_argument('--admission-stop', type=float, default=19.0); ap.add_argument('--epsilon', default='1/200'); ap.add_argument('--delta', default='1/1000000'); ap.add_argument('--seed', type=int, default=1); ap.add_argument('--lifted', action='store_true'); ap.add_argument('--no-pac', action='store_true'); ap.add_argument('--force-stream', default=None, choices=[None, 'original', 'lifted', 'joint'], help='DIAGNOSTIC: bypass only the offer decision and run one stream kind (never a production arm)'); ap.add_argument('--envelope', default='G1', choices=['G1', 'G2', 'G3', 'RMAX'], help='lifted upper envelope: G1 per-factor maxima (DGP2), G2 / G3 grouped joint maxima (DGP3 lemma G)'); ap.add_argument('--joint', default=None, choices=[None, 'seed', 'joint', 'cap_only', 'moment_only'], help='DGP5: the direct conditional proposal in the optional slot (seed = checked seed only; joint = + bounded joint updates; cap_only / moment_only = strategy ablations)'); a = ap.parse_args()
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), 'cex', 'newarm')); import core as CORE
    t0 = tnow()
    try: model, binding = CORE.read_uai(a.input)
    except (AssertionError, ValueError, StopIteration, OSError) as e:                                  # incompatible model / evidence binding: a typed task refusal, nothing published
        out = dict(version=VERSION, outcome='INVALID_TASK', guarantee='PARTIAL', published=0, K=0, answers=[], mechanism=dict(refusal=dict(kind='INVALID_TASK', reason=repr(e)[:300]), positive_mass_witness=None, termination='INVALID_TASK'), phases_s=dict(read=tnow() - t0), wall_s=tnow() - t0, input=os.path.abspath(a.input), argv=sys.argv[1:], hard_deadline_respected=True)
        UP.write_result(out, a.output, a.budget); print(json.dumps(dict(outcome='INVALID_TASK', reason=repr(e)[:200]))); return
    tread = tnow() - t0
    P = UPlanner(model, binding, a.budget, eps=F(a.epsilon), delta=F(a.delta), admission_stop_s=a.admission_stop, seed=a.seed, pac=not a.no_pac, lifted=(a.lifted or a.force_stream == 'lifted'), force_stream=a.force_stream, envelope=a.envelope, joint=(a.joint or ('joint' if a.force_stream == 'joint' else None))); out = P.run(); out['forced_stream'] = a.force_stream; out['envelope'] = a.envelope; out['joint_mode'] = P.joint
    out['phases_s']['read'] = tread; out['binding'] = binding; out['input'] = os.path.abspath(a.input); out['argv'] = sys.argv[1:]; out['process_start_to_read_s'] = t0 - T_PROCESS_START
    out = UP.write_result(out, a.output, a.budget)
    print(json.dumps(dict(outcome=out['outcome'], guarantee=out.get('guarantee'), published=out.get('published'), K=out.get('K'), wall_s=round(out['wall_s'], 3), streams=[(s['label'], s['stage'], s['draws'], s['published']) for s in out['streams']], route=out['mechanism'].get('route'), termination=out['mechanism'].get('termination'))))


if __name__ == '__main__': main()
