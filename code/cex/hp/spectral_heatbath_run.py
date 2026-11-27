"""DGP8 SPECTRAL_HEATBATH, part 4 (DGP9 REPAIRED): the standalone runner. One request: fix the ORIGINAL query inventory from the input BEFORE anything can refuse (review RV5), canonicalize (the accepted coarse_envelope.canonicalize), build
the checked spectral witness (spectral_witness.certify under the arm's proposal policy; typed refusal of this route on arity / hard zero / width / proof), choose x0 deterministically, certify p0 and the burn-in, plan the PREDETERMINED
checkpoint sequence (policy 'fixed' = DGP8: four geometric checkpoints to the frozen-rate N_max with delta_j = delta_sample / 4; policy 'revised' = DGP9 mechanism change B: a finite increasing sequence N_j = ceil(rho_N^(j-1) N_1) with
summable risks delta_j = delta_sample / (j (j + 1)), sampled as far as the work deadline permits), run the chain (the native exact-decision kernel when its all-assignment range witness admits it; otherwise the EXACT rational chain as the
checked fallback -- review RV1) through burn-in and the recorded window, snapshot the occupation counts at every COMPLETED checkpoint (immutable), build the rows of the LAST completed checkpoint under the accepted epsilon-safe J-box
publication (markov_certificate.rows_from_counts; review RV4), restore the canonical scalar in the original-Z enclosure (review RV5), assemble EVERY variable-size output before the ONE authoritative final timestamp, and suppress every new
row when that sample is late (outcome DEADLINE; review RV5). A requested rate-model file that is absent is a TYPED failure (RATE_MODEL_MISSING, exit 3), never a default rate (review RV7). Development mode `--dev-stream S`: witness + a
stream of S seconds of transitions + one measured checkpoint overhead, no publication (the screen's throughput / cost measurement; charged).
usage: spectral_heatbath_run.py --input M.uai --output OUT.json [--budget 19.5] [--admission-stop 19.0] [--seed 1] [--epsilon 1/200] [--delta 1/1000000] [--policy fixed|revised] [--dev-stream S] [--rate-model RATES.json] [--exact-chain]"""
import sys, os, json, time, math, argparse, hashlib, resource
from fractions import Fraction as F
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), 'cex', 'newarm')); sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), 'cex', 'blockres'))
import coarse_envelope as CE, core as CORE
import spectral_witness as SW, heatbath_exact as HX, heatbath_native as HN, markov_certificate as MC
from pac_actions import tnow
VERSION = 'spectral-heatbath-runner v0.2 (DGP9 27 Nov 2026): checked spectral witness (exact per-pair accumulation; frozen proposal-margin retries under policy revised) -> exact random-scan heat-bath on the original model (power-of-two normalized native kernel admitted by an all-assignment range witness, exact-rational chain as the checked fallback) -> the separate Markov confidence certificate (p0 / burn-in / Leon-Perron radius at predetermined checkpoints; summable risks under policy revised) -> accepted epsilon-safe J-box publication'
PROFILE = dict(beta_share=F(1, 2), delta_sample_share=F(1, 2), reserve_s=0.35, default_rate_steps_per_s=2000000.0, exact_chain_rate_steps_per_s=20000.0, batch_steps=200000, exact_batch_steps=2048, x0_rule='per variable the argmax of the unary weight (ties: smallest state)',
               fixed=dict(checkpoints_J=4, checkpoint_rule=MC.PROFILE['policies']['fixed']['checkpoint_rule'], delta_j_rule=MC.PROFILE['policies']['fixed']['delta_j_rule']),
               revised=dict(N1_rule='N_1 = ceil(N_floor / 8) with N_floor = frozen rate x available sampling seconds (the DGP8 first checkpoint)', rho_N='1.25', J_max=64, checkpoint_rule=MC.PROFILE['policies']['revised']['checkpoint_rule'], delta_j_rule=MC.PROFILE['policies']['revised']['delta_j_rule'], proposal_margins=SW.POLICY_REVISED['extra_margins']),
               publication='the LAST completed checkpoint; per variable the accepted epsilon-safe J-box points with endpoint radius <= eps and simplex feasibility verified; wider intervals recorded as enclosures')


def rate_for(rates, n, nf, cards):
    """the frozen work-rate model: steps / s = the recorded class (n, max card) else the global floor; returns (rate, record)"""
    if not rates: return PROFILE['default_rate_steps_per_s'], dict(source='absent: conservative default (no rate file requested)', steps_per_s=PROFILE['default_rate_steps_per_s'])
    key = '%d_%d' % (n, max(cards)); cls = (rates.get('classes') or {}).get(key)
    if cls: return float(cls['steps_per_s_floor']), dict(source='class %s' % key, **cls)
    return float(rates.get('floor_steps_per_s', PROFILE['default_rate_steps_per_s'])), dict(source='global floor', steps_per_s=rates.get('floor_steps_per_s'))


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--input', required=True); ap.add_argument('--output', required=True); ap.add_argument('--budget', type=float, default=19.5); ap.add_argument('--admission-stop', type=float, default=19.0); ap.add_argument('--seed', type=int, default=1); ap.add_argument('--epsilon', default='1/200'); ap.add_argument('--delta', default='1/1000000')
    ap.add_argument('--policy', default='fixed', choices=['fixed', 'revised']); ap.add_argument('--dev-stream', type=float, default=None); ap.add_argument('--rate-model', default=None); ap.add_argument('--exact-chain', action='store_true', help='CONTROLS: force the exact rational chain (the checked fallback) even when the native range witness admits the kernel')
    ap.add_argument('--plan-rho', default=None, help='override the frozen rho_N of policy revised (development only; the frozen value is in PROFILE)'); a = ap.parse_args()
    t_start = tnow(); hard = t_start + a.budget; work = t_start + a.admission_stop; eps = F(a.epsilon); delta = F(a.delta); ph = {}; policy = a.policy
    out = dict(version=VERSION, input=os.path.abspath(a.input), argv=sys.argv[1:], seed=a.seed, epsilon=str(eps), delta=str(delta), budget_s=a.budget, admission_stop_s=a.admission_stop, policy=policy, mechanism=dict(route='spectral_heatbath', policy=policy, refusal=None), Z=None, Z_enclosure=None, positive_mass_witness=None, K=0, answers=[], enclosures=[], published=0)
    mech = out['mechanism']; B = CE.Budget(CE.CONSTRUCTOR_BYTES); hclock = CE.Clock(hard, {}); wclock = CE.Clock(work, {}); chain_box = [None]; canonical_charge_box = [0]; witness_box = [None]; inventory = []; rows_none = []; exit_code = [0]
    def finish(outcome, rows=None, enc=None, note=None):
        """EVERY variable-size assembly happens BEFORE the one authoritative final timestamp (the kernel's storage and the retained witness fields are released first; rows / enclosures / counts / guarantee / resource diagnostics are
        all built here); the sample decides between the assembled rows and the pre-built NOT_PUBLISHED inventory (bounded choice); a late sample suppresses every new row (outcome DEADLINE)"""
        if note: mech['note'] = note
        if chain_box[0] is not None:
            try: mech['chain_record'] = chain_box[0].record()
            except Exception: pass
            chain_box[0].close(); chain_box[0] = None                                                     # the kernel's admitted bytes are released before the ledger identity is taken
        if witness_box[0] is not None: SW.release_retained(witness_box[0], B); witness_box[0] = None
        rows_pub = rows if rows is not None else list(rows_none); enc_pub = enc or []
        published_pub = sum(1 for r in rows_pub if r['guarantee'] != 'NOT_PUBLISHED'); gs_pub = {r['guarantee'] for r in rows_pub}
        guarantee_pub = ('PAC' if (gs_pub and 'NOT_PUBLISHED' not in gs_pub) else ('PARTIAL' if published_pub else 'NONE')) if rows_pub else 'NONE'
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss; live = B.live; ident = (B.live == canonical_charge_box[0]); phases = dict(ph)
        t_end = tnow()                                                                                     # the ONE authoritative final sample: nothing variable-size after it
        late = not (t_end <= hard)
        out['wall_s'] = t_end - t_start; out['hard_deadline_respected'] = (not late); out['peak_rss_bytes'] = rss; out['phases_s'] = phases; mech['constructor_live_at_end_bytes'] = live; mech['constructor_live_ledger_identity'] = ident
        if not late: out['answers'] = rows_pub; out['enclosures'] = enc_pub; out['published'] = published_pub; out['guarantee'] = guarantee_pub
        else: mech['suppressed_late_rows'] = published_pub; out['answers'] = rows_none; out['enclosures'] = []; out['published'] = 0; out['guarantee'] = 'NONE'; outcome = 'DEADLINE'
        out['outcome'] = outcome
        if outcome == 'COMPLETE' and out['guarantee'] != 'PAC': out['outcome'] = 'PARTIAL'
        json.dump(out, open(a.output, 'w'), indent=1, default=str); return out
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
        t0 = tnow(); cache = SW.LogCache(B, wclock, 'certificate log cache'); x0 = MC.choose_x0(hbm); lp0, W0 = MC.log_p0_lower(hbm, x0, cache); beta = delta * PROFILE['beta_share']; delta_sample = delta * PROFILE['delta_sample_share']
        t_burn, brec = MC.burn_in_steps(lp0, g, beta); lZU = MC.log_Z_upper(hbm, cache); sl, sh = SW.log_enclosure(M.scalar, cache); cache_rec = cache.record(); cache.release(); ph['certificate_setup'] = tnow() - t0
        zlo = W0 + sl; zhi = lZU + sh; z2lo, z2hi = SW.log_div_ln2_outward(zlo, zhi); f2lo, f2hi = SW.to_float_outward(z2lo, z2hi)
        mech['x0'] = dict(rule=PROFILE['x0_rule'], state=x0); mech['p0'] = dict(log2_p0_lower=float(SW.log_div_ln2_outward(lp0, lp0)[0]), ln_p0_lower=float(lp0), log2_Z_upper_canonical=float(SW.log_div_ln2_outward(lZU, lZU)[1]), ln_W_x0_lower=float(W0)); mech['burn_in'] = dict(steps=t_burn, beta=str(beta), **brec); mech['certificate_cache'] = cache_rec
        out['Z_enclosure'] = dict(log2_lo=f2lo, log2_hi=f2hi, ln_lo_exact=str(zlo), ln_hi_exact=str(zhi), canonical_scalar=str(M.scalar), note='ORIGINAL Z: ln Z in [ln W(x0) + ln scalar, ln Z_U + ln scalar] (W(x0) > 0 strict positivity; Z_U = prod k_i prod_f max f over the canonical model; the canonical scalar restored); base-2 by sign-aware outward division by the ln 2 enclosure; this route does not estimate Z'); out['positive_mass_witness'] = True
        # ---- the rate model and the chain (native when the range witness admits; else the exact chain)
        rate, rrec = rate_for(rates, n, len(hbm.pairs), hbm.cards); mech['rate_model'] = rrec; exact_chain = bool(a.exact_chain); t0 = tnow()
        if not exact_chain:
            try: chain = HN.NativeChain(hbm, x0, a.seed, wclock, budget=B); chain_box[0] = chain; mech['native_build'] = {k: chain.build_record.get(k) for k in ('source_sha256', 'binary_sha256', 'compiler', 'compiler_version', 'library', 'range_floor_log2')}; mech['chain'] = 'native'
            except HN.RefusedNative as e: mech['native_refusal'] = dict(kind=e.kind, reason=str(e.reason)[:200]); exact_chain = True
        if exact_chain:
            est = HX.exact_chain_bytes_estimate(hbm); owned = B.charge(est, 'exact heat-bath chain'); chain = HX.ExactChain(hbm, x0, a.seed, wclock); chain.owned_bytes = owned
            def _close(c=chain, b=B): b.release(c.owned_bytes); c.owned_bytes = 0
            chain.close = _close; chain_box[0] = chain; mech['chain'] = 'exact'; rate = PROFILE['exact_chain_rate_steps_per_s']; mech['rate_model'] = dict(source='exact chain: conservative constant', steps_per_s=rate, native_rate_record=rrec)
        ph['chain_construct'] = tnow() - t0; mech['bytes'] = dict(witness=W['bytes'], witness_retained=W.get('retained_bytes'), kernel=getattr(chain, 'bytes', None), occupation=8 * sum(hbm.cards) * 2, peak_admitted=B.peak); batch = PROFILE['batch_steps'] if mech['chain'] == 'native' else PROFILE['exact_batch_steps']
        if a.dev_stream is not None:
            # the screen's development stream: S seconds of transitions (no publication) + ONE measured checkpoint overhead (flush + rows) = the cost data for the frozen plan constants
            t1 = tnow(); done = 0
            while tnow() - t1 < a.dev_stream and tnow() < work: done += chain.run(batch, batch=batch, tag='dev')
            secs = tnow() - t1; c = chain.counters(); chain.set_recording(); done2 = chain.run(batch, batch=batch, tag='dev-record'); t2 = tnow(); occ = chain.flush(); rr = MC.radius_upper(done2, out['K'], delta_sample / 4, g); pub, enc, st = MC.rows_from_counts(occ, done2, rr, eps, M.orig_of, M.fixed_rows); cp_overhead = tnow() - t2
            mech['dev_stream'] = dict(seconds=secs, steps=done, steps_per_second=(done / secs if secs > 0 else None), fast_path_share=((c['resolved'] / max(1, c['resolved'] + c['exact_fallbacks'])) if (done and mech['chain'] == 'native') else None), counters=c, checkpoint_overhead_s=cp_overhead, checkpoint_overhead_rows=len(pub) + len(enc), chain=mech['chain'])
            r_meas = mech['dev_stream']['steps_per_second'] or rate; avail = a.admission_stop - ph['canonicalize'] - ph['witness'] - ph['certificate_setup'] - ph['chain_construct'] - PROFILE['reserve_s'] - (t_burn / r_meas); N_max = int(max(0.0, avail) * r_meas)
            J = PROFILE['fixed']['checkpoints_J']; dj = delta_sample / J; plan = MC.checkpoint_plan(N_max, J) if N_max > 0 else []
            mech['forecast'] = dict(steps_per_second_measured=r_meas, available_sampling_s=avail, N_max=N_max, burn_in_steps=t_burn, checkpoints=[dict(N=Nj, radius=float(MC.radius_upper(Nj, out['K'], dj, g))) for Nj in plan], radius_at_N_max=(float(MC.radius_upper(N_max, out['K'], dj, g)) if N_max > 0 else 1.0), completion_N=None)
            lo, hi = 1, 1 << 62
            while lo < hi:
                mid = (lo + hi) // 2
                if MC.radius_upper(mid, out['K'], dj, g) <= eps: hi = mid
                else: lo = mid + 1
            mech['forecast']['completion_N'] = lo; mech['forecast']['completion_seconds_at_rate'] = lo / r_meas; ph['dev_stream'] = secs; return finish('DEV_STREAM', note='development throughput stream (no publication)')
        # ---- production: the predetermined plan, burn-in, the recorded window
        avail = a.admission_stop - (tnow() - t_start) - PROFILE['reserve_s'] - (t_burn / rate); N_floor = int(max(0.0, avail) * rate)
        if policy == 'fixed':
            J = PROFILE['fixed']['checkpoints_J']; plan = MC.checkpoint_plan(N_floor, J) if N_floor > 0 else []; risks = MC.checkpoint_risks('fixed', delta_sample, len(plan)) if plan else []
            mech['checkpoint_plan'] = dict(policy='fixed', N_max=N_floor, plan=plan, delta_j=[str(d) for d in risks], beta=str(beta), delta_sample=str(delta_sample), rate_steps_per_s=rate, rule=PROFILE['fixed']['checkpoint_rule'], risk_rule=PROFILE['fixed']['delta_j_rule'], risk_sum=str(sum(risks, F(0))))
        else:
            rho = F(a.plan_rho) if a.plan_rho else F(PROFILE['revised']['rho_N']); J_max = PROFILE['revised']['J_max']; N1 = -(-N_floor // 8) if N_floor > 0 else 0; plan = MC.checkpoint_plan_revised(N1, rho, J_max) if N1 > 0 else []; risks = MC.checkpoint_risks('revised', delta_sample, len(plan)) if plan else []
            mech['checkpoint_plan'] = dict(policy='revised', N_floor=N_floor, N_1=N1, rho_N=str(rho), J_max=J_max, plan=plan, delta_j=[str(d) for d in risks], beta=str(beta), delta_sample=str(delta_sample), rate_steps_per_s=rate, rule=PROFILE['revised']['checkpoint_rule'], risk_rule=PROFILE['revised']['delta_j_rule'], risk_sum=str(sum(risks, F(0))), N1_rule=PROFILE['revised']['N1_rule'])
        assert sum(risks, F(0)) + beta <= delta, 'risk allocation exceeds delta'
        if not plan: mech['refusal'] = dict(kind='ALLOWANCE', reason='no sampling time remains after the witness and the burn-in forecast (%d steps at %.0f steps / s)' % (t_burn, rate)); return finish('REFUSED')
        t1 = tnow(); chain.run(t_burn, batch=batch, tag='burn-in'); ph['burn_in'] = tnow() - t1; chain.set_recording(); t_rec0 = chain.steps(); cps = []; t1 = tnow(); last = None; stop_reason = 'plan exhausted'
        for j, Nj in enumerate(plan):
            if tnow() >= work - PROFILE['reserve_s']: stop_reason = 'work allowance reached before checkpoint %d' % (j + 1); break
            need = Nj - (chain.steps() - t_rec0)
            if need > 0:
                try: chain.run(need, batch=batch, tag='checkpoint %d' % (j + 1))
                except CE.Refused as e:
                    if getattr(e, 'kind', None) != 'DEADLINE': raise
                    mech['checkpoint_interrupted'] = dict(index=j + 1, reason=str(getattr(e, 'reason', e))[:160], steps_done=chain.steps() - t_rec0); stop_reason = 'work clock expired inside checkpoint %d' % (j + 1); break           # the last COMPLETED checkpoint (if any) publishes
            t2 = tnow(); occ = chain.flush(); N = chain.steps() - t_rec0; assert N == Nj, (N, Nj)
            r = MC.radius_upper(N, out['K'], risks[j], g); pub, enc, st = MC.rows_from_counts(occ, N, r, eps, M.orig_of, M.fixed_rows)
            snap = dict(index=j + 1, N=N, delta_j=str(risks[j]), radius=float(r), max_width=st['max_width'], published_rows=len(pub), variables_published=st['variables_published'], enclosures=len(enc), completed=True, seconds=tnow() - t1, checkpoint_overhead_s=tnow() - t2, counters=chain.counters()); cps.append(snap); last = (occ, N, r, pub, enc, st, j)
        ph['sampling'] = tnow() - t1; mech['checkpoints'] = cps; mech['checkpoints_declared'] = len(plan); mech['checkpoints_completed'] = len(cps); mech['sampling_stop'] = stop_reason; c = chain.counters()
        mech['transitions'] = dict(total=chain.steps(), burn_in=t_burn, recorded=(chain.steps() - t_rec0), native_resolved=c.get('resolved'), exact_fallbacks=c.get('exact_fallbacks'), null_moves=c.get('null_moves'), poll_returns=c.get('poll_returns'), steps_per_second=((chain.steps()) / max(1e-9, (ph.get('burn_in', 0) + ph['sampling']))))
        if last is None: mech['refusal'] = dict(kind='DEADLINE', reason='no checkpoint completed inside the work allowance'); return finish('DEADLINE')
        occ, N, r, pub, enc, st, j_last = last; t2 = tnow(); rows = []
        for (x, v) in inventory:
            if (x, v) in M.fixed_rows: q, gq = M.fixed_rows[(x, v)]; rows.append(dict(var=x, state=v, lo=str(q), hi=str(q), point=str(q), guarantee=gq)); continue
            if (x, v) in pub: lo, hi, p, gg = pub[(x, v)]; rows.append(dict(var=x, state=v, lo=str(lo), hi=str(hi), point=str(p), guarantee=gg))
            else: rows.append(dict(var=x, state=v, guarantee='NOT_PUBLISHED'))
        enc_rows = [dict(var=x, state=v, lo=str(lo), hi=str(hi)) for (x, v, lo, hi) in enc]; ph['publication'] = tnow() - t2
        worst = max([float(F(rw['hi']) - F(rw['lo'])) / 2 for rw in rows if rw['guarantee'] != 'NOT_PUBLISHED'] + [float(F(e['hi']) - F(e['lo'])) / 2 for e in enc_rows] + [0.0])
        mech['certificate'] = dict(type='markov_heatbath', N=N, radius=float(r), checkpoint_index=j_last + 1, delta_j=str(risks[j_last]), beta=str(beta), total_failure_probability=str(beta + sum(risks, F(0))), worst_radius_on_inventory=worst, publication=dict(variables=st['variables'], variables_published=st['variables_published'], point_policy=st['point_policy_counts'], simplex_violations=st['simplex_violations'], endpoint_violations=st['endpoint_violations']), note='dependent-sample certificate; never mixed with the IID importance certificate; the union bound covers every DECLARED checkpoint')
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
