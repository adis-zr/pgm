"""DGP8 SPECTRAL_HEATBATH, part 4 (DGP9 REPAIRED; DGP10 QUERY RESPONSE v0.3): the standalone runner. One request: fix the ORIGINAL query inventory from the input BEFORE anything can refuse (review RV5), canonicalize (the accepted
coarse_envelope.canonicalize), build the checked spectral witness (spectral_witness.certify under the arm's proposal policy; typed refusal of this route on arity / hard zero / width / proof), choose x0 deterministically, certify p0 and the
burn-in, plan the PREDETERMINED checkpoint sequence (policy 'fixed' = DGP8: four geometric checkpoints to the frozen-rate N_max with delta_j = delta_sample / 4; policy 'revised' = DGP9 mechanism change B: a finite increasing sequence
N_j = ceil(rho_N^(j-1) N_1) with summable risks delta_j = delta_sample / (j (j + 1)), sampled as far as the work deadline permits), run the chain (the native exact-decision kernel when its all-assignment range witness admits it; otherwise
the EXACT rational chain as the checked fallback -- review RV1) through burn-in and the recorded window, snapshot the occupation counts at every COMPLETED checkpoint (immutable), build the rows of the LAST completed checkpoint under
the accepted epsilon-safe J-box publication (markov_certificate.rows_from_counts; review RV4), restore the canonical scalar in the original-Z enclosure (review RV5), assemble EVERY variable-size output before the ONE authoritative final
timestamp, and suppress every new row when that sample is late (outcome DEADLINE; review RV5). A requested rate-model file that is absent is a TYPED failure (RATE_MODEL_MISSING, exit 3), never a default rate (review RV7).
Development mode `--dev-stream S`: witness + a stream of S seconds of transitions + one measured checkpoint overhead, no publication (the screen's throughput / cost measurement; charged).
DGP10 (`--response`; theory sections 3-6, brief sections 2-6, FROZEN_EXPERIMENT_SPEC section 5): the SAME exact chain, witness, x0, burn-in (beta = delta / 2 once) and revised global plan, with (a) the raw occupation family at
delta / 4 (its checkpoint risks (delta / 4) / (j (j + 1))), (b) the native conditional-response OBSERVER on every active (canonical) variable -- the exact conditional of the selected site enclosed from the step's own outward bounds
and accumulated at the site's local visit clock, snapshots at the FROZEN local plan M_j = ceil(2^14 (5/4)^(j-1)) (j <= 64), started together with the recording after burn-in -- and (c) in a RESERVED tail after sampling the CHECKED
population-moment / two-state mean certificate per (j, k) group (response_certificate; the exact checker is the packet's reference), the per-coordinate intersection raw cap response, the accepted J-box publication from the
intersected boxes (markov_certificate.rows_from_boxes), an empty intersection = typed CONFLICT (nothing invented). Every unpublished coordinate's FINAL timely checked enclosure is written to `enclosures` (the partial-accuracy metric);
the same-path raw certificate at the FULL delta / 2 allocation is a NON-PUBLISHING diagnostic (`diagnostics.raw_full_delta_same_path`). When the native range witness refuses, the exact chain runs WITHOUT an observer and the arm
returns raw-only rows (recorded `response.unavailable`). Output commit (DGP9 review F9-1): both candidate payloads -- the intended result and its late-suppressed form -- are ENCODED before the one authoritative sample; the sample
chooses; the physical commit is one bounded placeholder substitution + one write; successful delivery additionally requires the supervisor's terminal receipt inside the outer contract.
usage: spectral_heatbath_run.py --input M.uai --output OUT.json [--budget 19.5] [--admission-stop 19.0] [--seed 1] [--epsilon 1/200] [--delta 1/1000000] [--policy fixed|revised] [--response] [--dev-stream S] [--rate-model RATES.json] [--exact-chain]"""
import sys, os, json, time, math, argparse, hashlib, resource
from fractions import Fraction as F
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), 'cex', 'newarm')); sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), 'cex', 'blockres'))
import coarse_envelope as CE, core as CORE
import spectral_witness as SW, heatbath_exact as HX, heatbath_native as HN, markov_certificate as MC, response_certificate as RC
from pac_actions import tnow
VERSION = 'spectral-heatbath-runner v0.3 (DGP10 27 Nov 2026): checked spectral witness (exact per-pair accumulation; frozen proposal-margin retries under policy revised; one reservation transaction) -> exact random-scan heat-bath on the original model (power-of-two normalized native kernel admitted by an all-assignment range witness decided by exact bit-length bounds, exact-rational chain as the checked fallback) -> the separate Markov confidence certificate (p0 / burn-in / Leon-Perron radius at predetermined checkpoints; summable risks under policy revised) [+ --response: native conditional-response observer at frozen local visit checkpoints, checked population-moment / two-state mean certificate (exact reference checker), raw cap response intersection] -> accepted epsilon-safe J-box publication; staged output commit'
PROFILE = dict(beta_share=F(1, 2), delta_sample_share=F(1, 2), reserve_s=0.35, default_rate_steps_per_s=2000000.0, exact_chain_rate_steps_per_s=20000.0, batch_steps=200000, exact_batch_steps=2048, x0_rule='per variable the argmax of the unary weight (ties: smallest state)',
               fixed=dict(checkpoints_J=4, checkpoint_rule=MC.PROFILE['policies']['fixed']['checkpoint_rule'], delta_j_rule=MC.PROFILE['policies']['fixed']['delta_j_rule']),
               revised=dict(N1_rule='N_1 = ceil(N_floor / 8) with N_floor = frozen rate x available sampling seconds (the DGP8 first checkpoint)', rho_N='1.25', J_max=64, checkpoint_rule=MC.PROFILE['policies']['revised']['checkpoint_rule'], delta_j_rule=MC.PROFILE['policies']['revised']['delta_j_rule'], proposal_margins=SW.POLICY_REVISED['extra_margins']),
               publication='the LAST completed checkpoint; per variable the accepted epsilon-safe J-box points with endpoint radius <= eps and simplex feasibility verified; wider intervals recorded as enclosures',
               response=dict(raw_share=F(1, 4), moment_share=F(1, 8), mean_share=F(1, 8), local_plan='M_j = ceil(2^14 (5/4)^(j - 1)), j = 1..64 (exact integers, strictly increasing; frozen before sampling)', J_local=64, M1=1 << 14,
                             tail_rule='reserved finalization tail before sampling: tail_s = tail_base_s + tail_per_group_s x min(tail_groups_cap, 2 x distinct cardinalities); FROZEN from the development cost data (controls/dev/cost: certificate 0.012-0.015 s per group, snapshot read < 1 ms, intersection ~2 ms, publication ~20 ms at K = 256) with margins >= 2.5x', tail_base_s=0.15, tail_per_group_s=0.04, tail_groups_cap=12,
                             rate_model='the RESPONSE arm plans its global checkpoints from its OWN frozen rate file (RESPONSE_RATES.json, measured with the observer on); the HB_R file is never replaced', checker=RC.PROFILE['reference'], publication='raw cap response per coordinate; accepted J-box points from the intersected box; empty intersection -> CONFLICT (variable not published; raw enclosure kept)'),
               output_commit='both payloads (intended / late-suppressed) encoded BEFORE the one authoritative sample; bounded placeholder substitution + one write after it; delivery under the outer contract is the supervisor receipt')
WALL_TOKEN = '"__WALL_S_PLACEHOLDER__"'


def rate_for(rates, n, nf, cards):
    """the frozen work-rate model: steps / s = the recorded class (n, max card) else the global floor; returns (rate, record)"""
    if not rates: return PROFILE['default_rate_steps_per_s'], dict(source='absent: conservative default (no rate file requested)', steps_per_s=PROFILE['default_rate_steps_per_s'])
    key = '%d_%d' % (n, max(cards)); cls = (rates.get('classes') or {}).get(key)
    if cls: return float(cls['steps_per_s_floor']), dict(source='class %s' % key, **cls)
    return float(rates.get('floor_steps_per_s', PROFILE['default_rate_steps_per_s'])), dict(source='global floor', steps_per_s=rates.get('floor_steps_per_s'))


def response_tail_s(cards):
    p = PROFILE['response']; return p['tail_base_s'] + p['tail_per_group_s'] * min(p['tail_groups_cap'], 2 * len(set(cards)))


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--input', required=True); ap.add_argument('--output', required=True); ap.add_argument('--budget', type=float, default=19.5); ap.add_argument('--admission-stop', type=float, default=19.0); ap.add_argument('--seed', type=int, default=1); ap.add_argument('--epsilon', default='1/200'); ap.add_argument('--delta', default='1/1000000')
    ap.add_argument('--policy', default='fixed', choices=['fixed', 'revised']); ap.add_argument('--dev-stream', type=float, default=None); ap.add_argument('--rate-model', default=None); ap.add_argument('--exact-chain', action='store_true', help='CONTROLS: force the exact rational chain (the checked fallback) even when the native range witness admits the kernel')
    ap.add_argument('--plan-rho', default=None, help='override the frozen rho_N of policy revised (development only; the frozen value is in PROFILE)'); ap.add_argument('--response', action='store_true', help='DGP10: the conditional-response observer + checked moment / mean certificate (requires policy revised)'); a = ap.parse_args()
    t_start = tnow(); hard = t_start + a.budget; work = t_start + a.admission_stop; eps = F(a.epsilon); delta = F(a.delta); ph = {}; policy = a.policy; response = bool(a.response)
    if response and policy != 'revised': raise SystemExit('--response requires --policy revised')
    out = dict(version=VERSION, input=os.path.abspath(a.input), argv=sys.argv[1:], seed=a.seed, epsilon=str(eps), delta=str(delta), budget_s=a.budget, admission_stop_s=a.admission_stop, policy=policy, response=response, mechanism=dict(route=('spectral_heatbath_response' if response else 'spectral_heatbath'), policy=policy, refusal=None), Z=None, Z_enclosure=None, positive_mass_witness=None, K=0, answers=[], enclosures=[], published=0, diagnostics={})
    mech = out['mechanism']; B = CE.Budget(CE.CONSTRUCTOR_BYTES); hclock = CE.Clock(hard, {}); wclock = CE.Clock(work, {}); chain_box = [None]; canonical_charge_box = [0]; witness_box = [None]; inventory = []; rows_none = []; exit_code = [0]
    def finish(outcome, rows=None, enc=None, note=None):
        """EVERY variable-size assembly happens BEFORE the one authoritative final timestamp (the kernel's storage and the retained witness fields are released first; rows / enclosures / counts / guarantee / resource diagnostics are
        all built here; DGP10 review F9-1: BOTH candidate payloads are JSON-ENCODED here too); the sample decides between the encoded intended payload and the encoded late-suppressed payload; the physical commit after the sample is
        one bounded placeholder substitution (the wall time) + one write. A late sample suppresses every new row (outcome DEADLINE)."""
        if note: mech['note'] = note
        if chain_box[0] is not None:
            try: mech['chain_record'] = chain_box[0].record()
            except Exception: pass
            chain_box[0].close(); chain_box[0] = None                                                     # the kernel's admitted bytes are released before the ledger identity is taken
        if witness_box[0] is not None: SW.release_retained(witness_box[0], B); witness_box[0] = None
        rows_pub = rows if rows is not None else list(rows_none); enc_pub = enc or []
        published_pub = sum(1 for r in rows_pub if r['guarantee'] != 'NOT_PUBLISHED'); gs_pub = {r['guarantee'] for r in rows_pub}
        guarantee_pub = ('PAC' if (gs_pub and 'NOT_PUBLISHED' not in gs_pub) else ('PARTIAL' if published_pub else 'NONE')) if rows_pub else 'NONE'
        if outcome == 'COMPLETE' and guarantee_pub != 'PAC': outcome = 'PARTIAL'
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss; live = B.live; ident = (B.live == canonical_charge_box[0]); phases = dict(ph)
        base = dict(out); base.update(peak_rss_bytes=rss, phases_s=phases); base['mechanism'] = dict(mech, constructor_live_at_end_bytes=live, constructor_live_ledger_identity=ident)
        A = dict(base, answers=rows_pub, enclosures=enc_pub, published=published_pub, guarantee=guarantee_pub, outcome=outcome, hard_deadline_respected=True, wall_s='__WALL_S_PLACEHOLDER__')
        L_ = dict(base, answers=rows_none, enclosures=[], published=0, guarantee='NONE', outcome='DEADLINE', hard_deadline_respected=False, wall_s='__WALL_S_PLACEHOLDER__'); L_['mechanism'] = dict(A['mechanism'], suppressed_late_rows=published_pub)
        sA = json.dumps(A, indent=1, default=str); sL = json.dumps(L_, indent=1, default=str); assert sA.count(WALL_TOKEN) == 1 and sL.count(WALL_TOKEN) == 1
        t_end = tnow()                                                                                     # the ONE authoritative final sample: nothing variable-size after it
        late = not (t_end <= hard); wall = t_end - t_start
        # the BOUNDED choice after the sample: one placeholder substitution on the pre-encoded payload + one write; the in-memory `out` mirrors the chosen payload (rows_pub when timely; rows_none + suppressed_late_rows when late)
        if not late: out['answers'] = rows_pub; out['enclosures'] = enc_pub; out['published'] = published_pub; out['guarantee'] = guarantee_pub; out['outcome'] = outcome; out['hard_deadline_respected'] = True; s = sA.replace(WALL_TOKEN, '%.9e' % wall, 1)
        else: mech['suppressed_late_rows'] = published_pub; out['answers'] = rows_none; out['enclosures'] = []; out['published'] = 0; out['guarantee'] = 'NONE'; out['outcome'] = 'DEADLINE'; out['hard_deadline_respected'] = False; s = sL.replace(WALL_TOKEN, '%.9e' % wall, 1)
        out['wall_s'] = wall
        with open(a.output, 'w') as f: f.write(s)
        return out
    try:
        # ---- the ORIGINAL query inventory first (before anything can refuse)
        t0 = tnow(); model, binding = CORE.read_uai(a.input); out['binding'] = binding
        cards_o = list(model['cards']); ev = dict(model.get('evidence', {})); inventory = [(x, v) for x in range(len(cards_o)) if x not in ev for v in range(cards_o[x])]; out['K'] = len(inventory)
        rows_none = [dict(var=x, state=v, guarantee='NOT_PUBLISHED') for (x, v) in inventory]; out['answers'] = rows_none
        # ---- the rate model: requested and absent -> typed failure (never a default rate)
        rates = None
        if a.rate_model:
            if not os.path.exists(a.rate_model): mech['refusal'] = dict(kind='RATE_MODEL_MISSING', reason='the requested frozen rate-model file is absent: %s' % a.rate_model); exit_code[0] = 3; return finish('REFUSED', note='requested rate model absent (typed failure; no default rate substituted)')
            rates = json.load(open(a.rate_model)); mech['rate_model_file'] = dict(path=os.path.abspath(a.rate_model), sha256=hashlib.sha256(open(a.rate_model, 'rb').read()).hexdigest())
        M = CE.canonicalize(model, hclock, B); ph['canonicalize'] = tnow() - t0; canonical_charge_box[0] = B.live; mech['canonical_charge_bytes'] = B.live; mech['canonical_scalar'] = str(M.scalar)
        if M.zero_mass: out['positive_mass_witness'] = False; out['Z_enclosure'] = dict(lo='0', hi='0'); return finish('ZERO_EVIDENCE', note='a canonical scalar is exactly zero')
        if not M.cards:                                                                                     # every variable fixed / factorless: exact rows only; Z = the scalar exactly
            rows = [dict(var=x, state=v, lo=str(M.fixed_rows[(x, v)][0]), hi=str(M.fixed_rows[(x, v)][0]), point=str(M.fixed_rows[(x, v)][0]), guarantee=M.fixed_rows[(x, v)][1]) if (x, v) in M.fixed_rows else dict(var=x, state=v, guarantee='NOT_PUBLISHED') for (x, v) in inventory]
            out['positive_mass_witness'] = True; sl, sh = SW.log_enclosure(M.scalar); l2lo, l2hi = SW.log_div_ln2_outward(sl, sh); out['Z_enclosure'] = dict(lo=str(M.scalar), hi=str(M.scalar), log2_lo=SW.to_float_outward(l2lo, l2hi)[0], log2_hi=SW.to_float_outward(l2lo, l2hi)[1], note='Z = the canonical scalar exactly (no retained variable)')
            return finish('COMPLETE' if all(r['guarantee'] != 'NOT_PUBLISHED' for r in rows) else 'PARTIAL', rows, [])
        # ---- the checked spectral witness (under the arm's proposal policy)
        t0 = tnow(); pol = SW.PROFILE['policies'][policy]
        try: W = SW.certify(M, B, wclock, policy=pol); witness_box[0] = W
        except SW.RefusedSpectral as e: mech['refusal'] = dict(kind=e.kind, reason=e.reason); ph['witness'] = tnow() - t0; return finish('REFUSED', note='the spectral heat-bath route refused typed (%s); no other route is affected' % e.kind)
        ph['witness'] = tnow() - t0; mech['witness'] = SW.witness_record(W); mech['witness']['seconds_verify'] = (W.get('proof') or {}).get('seconds_verify')
        if not W['eligible']: mech['refusal'] = W['refusal']; return finish('REFUSED', note='spectral eligibility refused: %s' % W['refusal']['reason'])
        g = F(W['g_exact']); n = len(M.cards); hbm = HX.HeatBathModel(M)
        # ---- x0, p0, burn-in, the original-Z enclosure WITH the canonical scalar
        t0 = tnow(); cache = SW.LogCache(B, wclock, 'certificate log cache'); x0 = MC.choose_x0(hbm); lp0, W0 = MC.log_p0_lower(hbm, x0, cache); beta = delta * PROFILE['beta_share']
        delta_sample = delta * (PROFILE['response']['raw_share'] if response else PROFILE['delta_sample_share'])
        t_burn, brec = MC.burn_in_steps(lp0, g, beta); lZU = MC.log_Z_upper(hbm, cache); sl, sh = SW.log_enclosure(M.scalar, cache); cache_rec = cache.record(); cache.release(); ph['certificate_setup'] = tnow() - t0
        zlo = W0 + sl; zhi = lZU + sh; z2lo, z2hi = SW.log_div_ln2_outward(zlo, zhi); f2lo, f2hi = SW.to_float_outward(z2lo, z2hi)
        mech['x0'] = dict(rule=PROFILE['x0_rule'], state=x0); mech['p0'] = dict(log2_p0_lower=float(SW.log_div_ln2_outward(lp0, lp0)[0]), ln_p0_lower=float(lp0), log2_Z_upper_canonical=float(SW.log_div_ln2_outward(lZU, lZU)[1]), ln_W_x0_lower=float(W0)); mech['burn_in'] = dict(steps=t_burn, beta=str(beta), **brec); mech['certificate_cache'] = cache_rec
        out['Z_enclosure'] = dict(log2_lo=f2lo, log2_hi=f2hi, ln_lo_exact=str(zlo), ln_hi_exact=str(zhi), canonical_scalar=str(M.scalar), note='ORIGINAL Z: ln Z in [ln W(x0) + ln scalar, ln Z_U + ln scalar] (W(x0) > 0 strict positivity; Z_U = prod k_i prod_f max f over the canonical model; the canonical scalar restored); base-2 by sign-aware outward division by the ln 2 enclosure; this route does not estimate Z'); out['positive_mass_witness'] = True
        # ---- the response allocation (frozen before sampling): eta, the local plan, the centers, the risk totals
        resp = None
        if response:
            eta = RC.eta_lower(g, n); local_plan = HN.local_checkpoint_plan(PROFILE['response']['J_local'], PROFILE['response']['M1']); centers = [HN.center_for(k) for k in hbm.cards]; n_q = n; Q = sum(hbm.cards)
            tot = RC.total_risk(delta, PROFILE['revised']['J_max'], PROFILE['response']['J_local']); assert tot <= delta, 'response risk allocation exceeds delta'
            resp = dict(eta=str(eta), eta_float=float(eta), eta_rule=RC.PROFILE['eta'], n_active=n, n_q=n_q, Q=Q, local_plan_rule=PROFILE['response']['local_plan'], local_plan_head=local_plan[:4], local_plan_J=len(local_plan), local_plan_last=local_plan[-1], centers={str(k): HN.center_for(k) for k in sorted(set(hbm.cards))}, B={str(k): str(RC.B_of(HN.center_for(k))) for k in sorted(set(hbm.cards))},
                        risks=dict(beta=str(beta), raw_total=str(delta * PROFILE['response']['raw_share']), moment_total=str(delta * PROFILE['response']['moment_share']), mean_total=str(delta * PROFILE['response']['mean_share']), weights='w_j = 1 / (j (j + 1))', per_variable_moment='delta w_j / (8 n_q)', per_coordinate_mean='delta w_j / (8 Q)', declared_total=str(tot), declared_total_le_delta=bool(tot <= delta)), tilts=RC.PROFILE['tilts'], checker=RC.PROFILE['reference'], tail_s=response_tail_s(hbm.cards), tail_rule=PROFILE['response']['tail_rule'], unavailable=None)
            mech['response'] = resp
        # ---- the rate model and the chain (native when the range witness admits; else the exact chain)
        rate, rrec = rate_for(rates, n, len(hbm.pairs), hbm.cards); mech['rate_model'] = rrec; exact_chain = bool(a.exact_chain); t0 = tnow()
        if not exact_chain:
            try: chain = HN.NativeChain(hbm, x0, a.seed, wclock, budget=B, observer=(dict(sites=list(range(n)), centers=centers, plan=local_plan) if response else None)); chain_box[0] = chain; mech['native_build'] = {k: chain.build_record.get(k) for k in ('source_sha256', 'binary_sha256', 'compiler', 'compiler_version', 'library', 'range_floor_log2')}; mech['chain'] = 'native'
            except HN.RefusedNative as e: mech['native_refusal'] = dict(kind=e.kind, reason=str(e.reason)[:200]); exact_chain = True
        if exact_chain:
            est = HX.exact_chain_bytes_estimate(hbm); owned = B.charge(est, 'exact heat-bath chain'); chain = HX.ExactChain(hbm, x0, a.seed, wclock); chain.owned_bytes = owned
            def _close(c=chain, b=B): b.release(c.owned_bytes); c.owned_bytes = 0
            chain.close = _close; chain_box[0] = chain; mech['chain'] = 'exact'; rate = PROFILE['exact_chain_rate_steps_per_s']; mech['rate_model'] = dict(source='exact chain: conservative constant', steps_per_s=rate, native_rate_record=rrec)
            if response: resp['unavailable'] = 'exact chain fallback (no native observer): raw-only rows at the response allocation (delta / 4)'
        ph['chain_construct'] = tnow() - t0; mech['bytes'] = dict(witness=W['bytes'], witness_retained=W.get('retained_bytes'), kernel=getattr(chain, 'bytes', None), observer=(getattr(chain, 'obs_bytes', None) if response else None), occupation=8 * sum(hbm.cards) * 2, peak_admitted=B.peak); batch = PROFILE['batch_steps'] if mech['chain'] == 'native' else PROFILE['exact_batch_steps']
        tail = response_tail_s(hbm.cards) if response else 0.0
        if a.dev_stream is not None:
            # the screen's development stream: S seconds of transitions (no publication) + ONE measured checkpoint overhead (flush + rows) = the cost data for the frozen plan constants; with --response the observer is ON during the stream
            t1 = tnow(); done = 0
            if response and mech['chain'] == 'native': chain.observer_start()
            while tnow() - t1 < a.dev_stream and tnow() < work: done += chain.run(batch, batch=batch, tag='dev')
            secs = tnow() - t1; c = chain.counters(); chain.set_recording(); done2 = chain.run(batch, batch=batch, tag='dev-record'); t2 = tnow(); occ = chain.flush(); rr = MC.radius_upper(done2, out['K'], delta_sample / 4, g); pub, enc, st = MC.rows_from_counts(occ, done2, rr, eps, M.orig_of, M.fixed_rows); cp_overhead = tnow() - t2
            mech['dev_stream'] = dict(seconds=secs, steps=done, steps_per_second=(done / secs if secs > 0 else None), fast_path_share=((c['resolved'] / max(1, c['resolved'] + c['exact_fallbacks'])) if (done and mech['chain'] == 'native') else None), counters=c, checkpoint_overhead_s=cp_overhead, checkpoint_overhead_rows=len(pub) + len(enc), chain=mech['chain'], observer_on=bool(response and mech['chain'] == 'native'))
            if response and mech['chain'] == 'native':
                t3 = tnow(); snaps = chain.observer_snapshots(); rc_ = RC.response_intervals(snaps, eta, delta, n_q, Q, clock=wclock, deadline=work - PROFILE['reserve_s']); t4 = tnow()
                mech['dev_stream']['observer'] = dict(state=chain.observer_state(), snapshots_completed=sum(1 for s_ in snaps if s_['j'] is not None), groups=rc_['n_groups'], certified=rc_['n_certified'], checker_calls=rc_['checker_calls'], certificate_seconds=t4 - t3, seconds_per_group=((t4 - t3) / max(1, rc_['n_groups'])), groups_record=rc_['groups'][:6])
            r_meas = mech['dev_stream']['steps_per_second'] or rate; avail = a.admission_stop - ph['canonicalize'] - ph['witness'] - ph['certificate_setup'] - ph['chain_construct'] - PROFILE['reserve_s'] - tail - (t_burn / r_meas); N_max = int(max(0.0, avail) * r_meas)
            J = PROFILE['fixed']['checkpoints_J']; dj = delta_sample / J; plan = MC.checkpoint_plan(N_max, J) if N_max > 0 else []
            mech['forecast'] = dict(steps_per_second_measured=r_meas, available_sampling_s=avail, N_max=N_max, burn_in_steps=t_burn, checkpoints=[dict(N=Nj, radius=float(MC.radius_upper(Nj, out['K'], dj, g))) for Nj in plan], radius_at_N_max=(float(MC.radius_upper(N_max, out['K'], dj, g)) if N_max > 0 else 1.0), completion_N=None)
            lo, hi = 1, 1 << 62
            while lo < hi:
                mid = (lo + hi) // 2
                if MC.radius_upper(mid, out['K'], dj, g) <= eps: hi = mid
                else: lo = mid + 1
            mech['forecast']['completion_N'] = lo; mech['forecast']['completion_seconds_at_rate'] = lo / r_meas; ph['dev_stream'] = secs; return finish('DEV_STREAM', note='development throughput stream (no publication)')
        # ---- production: the predetermined plan, burn-in, the recorded window
        avail = a.admission_stop - (tnow() - t_start) - PROFILE['reserve_s'] - tail - (t_burn / rate); N_floor = int(max(0.0, avail) * rate)
        if policy == 'fixed':
            J = PROFILE['fixed']['checkpoints_J']; plan = MC.checkpoint_plan(N_floor, J) if N_floor > 0 else []; risks = MC.checkpoint_risks('fixed', delta_sample, len(plan)) if plan else []
            mech['checkpoint_plan'] = dict(policy='fixed', N_max=N_floor, plan=plan, delta_j=[str(d) for d in risks], beta=str(beta), delta_sample=str(delta_sample), rate_steps_per_s=rate, rule=PROFILE['fixed']['checkpoint_rule'], risk_rule=PROFILE['fixed']['delta_j_rule'], risk_sum=str(sum(risks, F(0))))
        else:
            rho = F(a.plan_rho) if a.plan_rho else F(PROFILE['revised']['rho_N']); J_max = PROFILE['revised']['J_max']; N1 = -(-N_floor // 8) if N_floor > 0 else 0; plan = MC.checkpoint_plan_revised(N1, rho, J_max) if N1 > 0 else []; risks = MC.checkpoint_risks('revised', delta_sample, len(plan)) if plan else []
            mech['checkpoint_plan'] = dict(policy='revised', N_floor=N_floor, N_1=N1, rho_N=str(rho), J_max=J_max, plan=plan, delta_j=[str(d) for d in risks], beta=str(beta), delta_sample=str(delta_sample), rate_steps_per_s=rate, rule=PROFILE['revised']['checkpoint_rule'], risk_rule=PROFILE['revised']['delta_j_rule'], risk_sum=str(sum(risks, F(0))), N1_rule=PROFILE['revised']['N1_rule'], response_tail_s=tail)
        assert sum(risks, F(0)) + beta <= delta, 'risk allocation exceeds delta'
        if not plan: mech['refusal'] = dict(kind='ALLOWANCE', reason='no sampling time remains after the witness and the burn-in forecast (%d steps at %.0f steps / s)' % (t_burn, rate)); return finish('REFUSED')
        t1 = tnow(); chain.run(t_burn, batch=batch, tag='burn-in'); ph['burn_in'] = tnow() - t1; chain.set_recording()
        observer_on = bool(response and mech['chain'] == 'native')
        if observer_on: chain.observer_start()
        t_rec0 = chain.steps(); cps = []; t1 = tnow(); last = None; stop_reason = 'plan exhausted'; sampling_end = work - PROFILE['reserve_s'] - tail
        if response: chain.clock = CE.Clock(sampling_end, {})                                                      # DGP10: the recorded window is BOUNDED by the sampling end (the reserved tail is never consumed by an overshooting checkpoint); HB_R keeps the DGP9 behaviour (work clock)
        for j, Nj in enumerate(plan):
            if tnow() >= sampling_end: stop_reason = 'work allowance reached before checkpoint %d' % (j + 1); break
            need = Nj - (chain.steps() - t_rec0)
            if need > 0:
                try: chain.run(need, batch=batch, tag='checkpoint %d' % (j + 1))
                except CE.Refused as e:
                    if getattr(e, 'kind', None) != 'DEADLINE': raise
                    mech['checkpoint_interrupted'] = dict(index=j + 1, reason=str(getattr(e, 'reason', e))[:160], steps_done=chain.steps() - t_rec0); stop_reason = 'work clock expired inside checkpoint %d' % (j + 1); break           # the last COMPLETED checkpoint (if any) publishes
            t2 = tnow(); occ = chain.flush(); N = chain.steps() - t_rec0; assert N == Nj, (N, Nj)
            r = MC.radius_upper(N, out['K'], risks[j], g); pub, enc, st = MC.rows_from_counts(occ, N, r, eps, M.orig_of, M.fixed_rows)
            snap = dict(index=j + 1, N=N, delta_j=str(risks[j]), radius=float(r), max_width=st['max_width'], published_rows=len(pub), variables_published=st['variables_published'], enclosures=len(enc), completed=True, seconds=tnow() - t1, checkpoint_overhead_s=tnow() - t2, counters=chain.counters()); cps.append(snap); last = (occ, N, r, pub, enc, st, j)
        ph['sampling'] = tnow() - t1; mech['checkpoints'] = cps; mech['checkpoints_declared'] = len(plan); mech['checkpoints_completed'] = len(cps); mech['sampling_stop'] = stop_reason; c = chain.counters(); chain.clock = wclock
        mech['transitions'] = dict(total=chain.steps(), burn_in=t_burn, recorded=(chain.steps() - t_rec0), native_resolved=c.get('resolved'), exact_fallbacks=c.get('exact_fallbacks'), null_moves=c.get('null_moves'), poll_returns=c.get('poll_returns'), steps_per_second=((chain.steps()) / max(1e-9, (ph.get('burn_in', 0) + ph['sampling']))))
        if observer_on: chain.observer_stop(); resp['observer_state'] = chain.observer_state()
        if last is None: mech['refusal'] = dict(kind='DEADLINE', reason='no checkpoint completed inside the work allowance'); return finish('DEADLINE')
        occ, N, r, pub, enc, st, j_last = last; t2 = tnow()
        # ---- DGP10: the response tail -- snapshots, the checked certificate per group, the intersection, the J-box publication from the intersected boxes
        boxes_raw = [[(max(F(0), F(int(c_), N) - r), min(F(1), F(int(c_), N) + r)) for c_ in row] for row in occ]; conflicts = []; resp_rows = None
        if observer_on and resp['observer_state']['valid']:
            try:
                t3 = tnow(); snaps = chain.observer_snapshots(); ph['response_snapshots'] = tnow() - t3; t3 = tnow()
                rc_ = RC.response_intervals(snaps, eta, delta, n_q, Q, clock=wclock, deadline=work - PROFILE['reserve_s']); ph['response_certificate'] = tnow() - t3; t3 = tnow()
                boxes = []; n_resp = 0; n_raw_only = 0
                for i in range(n):
                    ps = rc_['per_site'].get(i)
                    if ps is None: boxes.append(boxes_raw[i]); n_raw_only += 1; continue
                    box, conflict = RC.intersect_boxes(boxes_raw[i], ps['coords'])
                    if conflict: conflicts.append(dict(var=M.orig_of[i], canonical=i, raw=[(str(l_), str(h_)) for l_, h_ in boxes_raw[i]], response=[(str(c_['lo']), str(c_['hi'])) for c_ in ps['coords']])); boxes.append(boxes_raw[i]); continue
                    boxes.append(box); n_resp += 1
                pub2, enc2, st2 = MC.rows_from_boxes(boxes, eps, M.orig_of, M.fixed_rows); ph['response_intersection'] = tnow() - t3
                radii_resp = [float(c_['hi'] - c_['lo']) / 2 for ps in rc_['per_site'].values() for c_ in ps['coords']]; radii_raw = [float(h_ - l_) / 2 for row in boxes_raw for (l_, h_) in row]; radii_int = [float(h_ - l_) / 2 for row in boxes for (l_, h_) in row]
                resp.update(executed=True, snapshots=[dict(site=s_['site'], var=M.orig_of[s_['site']], k=s_['k'], j=s_['j'], M=s_['M'], count=s_['count'], center=s_['center']) for s_ in snaps], local_counts=dict(min=min(s_['count'] for s_ in snaps), max=max(s_['count'] for s_ in snaps), completed_j=sorted({s_['j'] for s_ in snaps if s_['j'] is not None}), sites_without_checkpoint=sum(1 for s_ in snaps if s_['j'] is None)),
                            groups=rc_['groups'], n_groups=rc_['n_groups'], n_certified=rc_['n_certified'], checker_calls=rc_['checker_calls'], unavailable_sites=rc_['unavailable'], variables_with_response=n_resp, variables_raw_only=n_raw_only, conflicts=conflicts,
                            per_coordinate=[dict(var=M.orig_of[s_['site']], state=a_, lo=str(c_['lo']), hi=str(c_['hi']), mean_lo=str(c_['mean_lo']), mean_hi=str(c_['mean_hi']), R=str(c_['R']), arith_width=float(c_['arith_width']), y_upper=float(c_['y_upper'])) for s_ in snaps if s_['site'] in rc_['per_site'] for a_, c_ in enumerate(rc_['per_site'][s_['site']]['coords'])],
                            radius=dict(response_worst=(max(radii_resp) if radii_resp else None), response_median=(sorted(radii_resp)[len(radii_resp) // 2] if radii_resp else None), raw_worst=(max(radii_raw) if radii_raw else None), intersected_worst=(max(radii_int) if radii_int else None), statistical_R_by_group={'%s/%s' % (g_['j'], g_['k']): float(F(g_['R'])) for g_ in rc_['groups'] if g_.get('available')}, arithmetic_width_max=(max(float(c_['arith_width']) for ps in rc_['per_site'].values() for c_ in ps['coords']) if rc_['per_site'] else None)),
                            publication=dict(variables=st2['variables'], variables_published=st2['variables_published'], point_policy=st2['point_policy_counts'], simplex_violations=st2['simplex_violations'], endpoint_violations=st2['endpoint_violations']))
                resp_rows = (pub2, enc2, st2)
            except CE.Refused as e: resp.update(executed=False, unavailable='%s: %s' % (e.kind, str(e.reason)[:160]))
        elif observer_on: resp.update(executed=False, unavailable='observer invalidated typed: %s' % resp['observer_state'].get('invalid_reason'))
        if resp_rows is not None: pub, enc, st = resp_rows
        rows = []
        for (x, v) in inventory:
            if (x, v) in M.fixed_rows: q, gq = M.fixed_rows[(x, v)]; rows.append(dict(var=x, state=v, lo=str(q), hi=str(q), point=str(q), guarantee=gq)); continue
            if (x, v) in pub: lo, hi, p, gg = pub[(x, v)]; rows.append(dict(var=x, state=v, lo=str(lo), hi=str(hi), point=str(p), guarantee=gg))
            else: rows.append(dict(var=x, state=v, guarantee='NOT_PUBLISHED'))
        enc_rows = [dict(var=x, state=v, lo=str(lo), hi=str(hi)) for (x, v, lo, hi) in enc]; ph['publication'] = tnow() - t2
        worst = max([float(F(rw['hi']) - F(rw['lo'])) / 2 for rw in rows if rw['guarantee'] != 'NOT_PUBLISHED'] + [float(F(e['hi']) - F(e['lo'])) / 2 for e in enc_rows] + [0.0])
        mech['certificate'] = dict(type=('markov_heatbath_response' if resp_rows is not None else 'markov_heatbath'), N=N, radius=float(r), checkpoint_index=j_last + 1, delta_j=str(risks[j_last]), beta=str(beta), total_failure_probability=str(beta + sum(risks, F(0)) + ((delta * (PROFILE['response']['moment_share'] + PROFILE['response']['mean_share'])) if response else 0)), worst_radius_on_inventory=worst, publication=dict(variables=st['variables'], variables_published=st['variables_published'], point_policy=st['point_policy_counts'], simplex_violations=st['simplex_violations'], endpoint_violations=st['endpoint_violations']), note='dependent-sample certificate; never mixed with the IID importance certificate; the union bound covers every DECLARED checkpoint (raw global + response local)')
        if response:
            # NON-PUBLISHING same-path diagnostic: the raw certificate at the FULL HB_R allocation (delta / 2 with its own w_j) on the same counts, and the raw-only reduced-allocation radius actually used
            r_full = MC.radius_upper(N, out['K'], (delta * PROFILE['delta_sample_share']) / ((j_last + 1) * (j_last + 2)), g)
            out['diagnostics']['raw_full_delta_same_path'] = dict(radius=float(r_full), allocation='delta / 2 x w_j (the HB_R policy) on the SAME occupation counts; NOT published, NOT in any gate', raw_reduced_radius=float(r), raw_reduced_allocation='delta / 4 x w_j (the RESPONSE raw family)')
        return finish('COMPLETE' if all(rw['guarantee'] != 'NOT_PUBLISHED' for rw in rows) else 'PARTIAL', rows, enc_rows)
    except CE.Refused as e:
        mech['refusal'] = dict(kind=e.kind, reason=str(e.reason)[:200]); return finish('DEADLINE' if e.kind == 'DEADLINE' else 'REFUSED')            # CE.Clock.poll raises Refused('DEADLINE'); every other kind is a typed resource refusal
    except Exception as e:
        import traceback; mech['refusal'] = dict(kind='INTERNAL', reason=repr(e)[:200]); mech['traceback'] = traceback.format_exc()[-2000:]; return finish('REFUSED')
    finally:
        if chain_box[0] is not None: chain_box[0].close(); chain_box[0] = None
        if witness_box[0] is not None: SW.release_retained(witness_box[0], B); witness_box[0] = None
        if exit_code[0]: sys.exit(exit_code[0])


if __name__ == '__main__': main()
