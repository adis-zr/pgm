"""DGP8 SPECTRAL_HEATBATH, part 4: the standalone runner (brief sections 1-6). One request: read the model (+ evidence), canonicalize (the accepted coarse_envelope.canonicalize: evidence restricted out, unaries absorbed, card-1 /
factorless variables fixed with EXACT rows), build the checked spectral witness (spectral_witness.certify; typed refusal of this route on arity / hard zero / width / proof), choose x0 deterministically, certify p0 and the burn-in,
plan the FROZEN checkpoint sequence from the frozen work-rate model (HEATBATH_RATES.json; steps per second per input class; absent -> a conservative default and the run is labelled 'rate model absent'), run the native exact-decision
heat-bath chain (heatbath_native.NativeChain) through burn-in and the recorded window, snapshot the occupation counts at every COMPLETED checkpoint (immutable), build the rows of the LAST completed checkpoint under the accepted
publication geometry (markov_certificate.rows_from_counts), and finish with the ONE authoritative final timestamp (a late sample suppresses every new row; outcome DEADLINE). Development mode `--dev-stream S`: witness + a stream
of S seconds of native transitions, no publication (the Stage A throughput measurement; charged). Output schema: see the module docstring of run_dgp8.py / dgp8_analyze.py (outcome, guarantee, published, K, answers, enclosures, Z,
Z_enclosure, positive_mass_witness, wall_s, hard_deadline_respected, mechanism{route, refusal, witness, x0, p0, burn_in, checkpoints, transitions, rate_model, phases_s, bytes, dev_stream}).
usage: spectral_heatbath_run.py --input M.uai --output OUT.json [--budget 19.5] [--admission-stop 19.0] [--seed 1] [--epsilon 1/200] [--delta 1/1000000] [--dev-stream S] [--rate-model RATES.json]"""
import sys, os, json, time, math, argparse, hashlib, resource
from fractions import Fraction as F
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), 'cex', 'newarm')); sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), 'cex', 'blockres'))
import coarse_envelope as CE, core as CORE
import spectral_witness as SW, heatbath_exact as HX, heatbath_native as HN, markov_certificate as MC
from pac_actions import tnow
VERSION = 'spectral-heatbath-runner v0.1 (DGP8 26 Nov 2026): checked spectral witness (interval matrix + interval Cholesky) -> exact random-scan heat-bath on the original model (native exact-decision fast path, exact fallback) -> the separate Markov confidence certificate (p0 / burn-in / Leon-Perron radius at frozen checkpoints)'
PROFILE = dict(beta_share=F(1, 2), delta_sample_share=F(1, 2), checkpoints_J=MC.PROFILE['checkpoints_J'], reserve_s=0.35, default_rate_steps_per_s=2000000.0, batch_steps=200000, x0_rule='per variable the argmax of the unary weight (ties: smallest state)', checkpoint_rule=MC.PROFILE['checkpoint_rule'], publication='the LAST completed checkpoint; rows by the accepted valid_publication geometry; wider intervals recorded as enclosures')


def rate_for(rates, n, nf, cards):
    """the frozen work-rate model: steps / s = min over the recorded classes matching (n, card) else the global floor; returns (rate, record)"""
    if not rates: return PROFILE['default_rate_steps_per_s'], dict(source='absent: conservative default', steps_per_s=PROFILE['default_rate_steps_per_s'])
    key = '%d_%d' % (n, max(cards)); cls = (rates.get('classes') or {}).get(key)
    if cls: return float(cls['steps_per_s_floor']), dict(source='class %s' % key, **cls)
    return float(rates.get('floor_steps_per_s', PROFILE['default_rate_steps_per_s'])), dict(source='global floor', steps_per_s=rates.get('floor_steps_per_s'))


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--input', required=True); ap.add_argument('--output', required=True); ap.add_argument('--budget', type=float, default=19.5); ap.add_argument('--admission-stop', type=float, default=19.0); ap.add_argument('--seed', type=int, default=1); ap.add_argument('--epsilon', default='1/200'); ap.add_argument('--delta', default='1/1000000'); ap.add_argument('--dev-stream', type=float, default=None); ap.add_argument('--rate-model', default=None); a = ap.parse_args()
    t_start = tnow(); hard = t_start + a.budget; work = t_start + a.admission_stop; eps = F(a.epsilon); delta = F(a.delta); ph = {}; out = dict(version=VERSION, input=os.path.abspath(a.input), argv=sys.argv[1:], seed=a.seed, epsilon=str(eps), delta=str(delta), budget_s=a.budget, admission_stop_s=a.admission_stop, mechanism=dict(route='spectral_heatbath', refusal=None), Z=None, Z_enclosure=None, positive_mass_witness=None, answers=[], enclosures=[], published=0, K=0)
    mech = out['mechanism']; B = CE.Budget(CE.CONSTRUCTOR_BYTES); hclock = CE.Clock(hard, {}); wclock = CE.Clock(work, {}); chain_box = [None]; canonical_charge_box = [0]
    def finish(outcome, rows=None, enc=None, note=None):
        """ONE authoritative final timestamp AFTER every publication diagnostic and after the kernel's storage is released; a late sample suppresses every new row (outcome DEADLINE)"""
        if note: mech['note'] = note
        if chain_box[0] is not None: chain_box[0].close(); chain_box[0] = None                                                     # the kernel's admitted bytes are released before the ledger identity is taken
        t_end = tnow(); out['wall_s'] = t_end - t_start; out['hard_deadline_respected'] = (t_end <= hard); out['peak_rss_bytes'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss; out['phases_s'] = ph; mech['constructor_live_at_end_bytes'] = B.live; mech['constructor_live_ledger_identity'] = (B.live == canonical_charge_box[0])
        if rows is not None and out['hard_deadline_respected']:
            out['answers'] = rows; out['enclosures'] = enc or []; out['published'] = sum(1 for r in rows if r['guarantee'] != 'NOT_PUBLISHED')
        elif rows is not None: mech['suppressed_late_rows'] = sum(1 for r in rows if r['guarantee'] != 'NOT_PUBLISHED'); out['answers'] = [dict(var=r['var'], state=r['state'], guarantee='NOT_PUBLISHED') for r in rows]; out['enclosures'] = []; out['published'] = 0; outcome = 'DEADLINE'
        gs = {r['guarantee'] for r in out['answers']}
        out['guarantee'] = ('PAC' if (gs and 'NOT_PUBLISHED' not in gs) else ('PARTIAL' if out['published'] else 'NONE')) if out['answers'] else 'NONE'
        out['outcome'] = outcome
        if outcome == 'COMPLETE' and out['guarantee'] != 'PAC': out['outcome'] = 'PARTIAL'
        json.dump(out, open(a.output, 'w'), indent=1, default=str); return out
    try:
        t0 = tnow(); model, binding = CORE.read_uai(a.input); out['binding'] = binding; M = CE.canonicalize(model, hclock, B); ph['canonicalize'] = tnow() - t0; canonical_charge_box[0] = B.live; mech['canonical_charge_bytes'] = B.live
        cards_o = list(model['cards']); ev = dict(model.get('evidence', {})); queries = [(x, v) for x in range(len(cards_o)) if x not in ev for v in range(cards_o[x])]; out['K'] = len(queries); qix = {q: j for j, q in enumerate(queries)}
        if M.zero_mass: out['positive_mass_witness'] = False; out['Z_enclosure'] = dict(lo='0', hi='0'); return finish('ZERO_EVIDENCE', note='a canonical scalar is exactly zero')
        if not M.cards:                                                                                     # every variable fixed / factorless: exact rows only
            rows = [dict(var=x, state=v, lo=str(M.fixed_rows[(x, v)][0]), hi=str(M.fixed_rows[(x, v)][0]), point=str(M.fixed_rows[(x, v)][0]), guarantee=M.fixed_rows[(x, v)][1]) if (x, v) in M.fixed_rows else dict(var=x, state=v, guarantee='NOT_PUBLISHED') for (x, v) in queries]       # canonicalize's fixed rows are (Fraction, 'EXACT')
            out['positive_mass_witness'] = True; return finish('COMPLETE' if all(r['guarantee'] != 'NOT_PUBLISHED' for r in rows) else 'PARTIAL', rows, [])
        # ---- the checked spectral witness
        t0 = tnow()
        try: W = SW.certify(M, B, wclock)
        except SW.RefusedSpectral as e: mech['refusal'] = dict(kind=e.kind, reason=e.reason); ph['witness'] = tnow() - t0; return finish('REFUSED', note='the spectral heat-bath route refused typed (%s); no other route is affected' % e.kind)
        ph['witness'] = tnow() - t0; mech['witness'] = SW.witness_record(W); mech['witness']['seconds_verify'] = (W.get('proof') or {}).get('seconds_verify')
        if not W['eligible']: mech['refusal'] = W['refusal']; return finish('REFUSED', note='spectral eligibility refused: %s' % W['refusal']['reason'])
        g = F(W['g_exact']); n = len(M.cards); hbm = HX.HeatBathModel(M)
        # ---- x0, p0, burn-in
        t0 = tnow(); x0 = MC.choose_x0(hbm); lp0, W0 = MC.log_p0_lower(hbm, x0); beta = delta * PROFILE['beta_share']; delta_sample = delta * PROFILE['delta_sample_share']
        t_burn, brec = MC.burn_in_steps(lp0, g, beta); ph['certificate_setup'] = tnow() - t0; lZU = MC.log_Z_upper(hbm)
        mech['x0'] = dict(rule=PROFILE['x0_rule'], state=x0); mech['p0'] = dict(log2_p0_lower=float(lp0 / SW.log2_enclosure()[0]), ln_p0_lower=float(lp0), log2_Z_upper=float(lZU / SW.log2_enclosure()[0]), ln_W_x0_lower=float(W0)); mech['burn_in'] = dict(steps=t_burn, beta=str(beta), **brec)
        out['Z_enclosure'] = dict(log2_lo=float(W0 / SW.log2_enclosure()[0]), log2_hi=mech['p0']['log2_Z_upper'], note='Z >= W(x0) > 0 (strict positivity; ln W(x0) lower enclosure); Z <= Z_U = prod k_i prod_f max f (upper enclosure); this route does not estimate Z'); out['positive_mass_witness'] = True
        # ---- the rate model and the frozen checkpoint plan
        rates = json.load(open(a.rate_model)) if (a.rate_model and os.path.exists(a.rate_model)) else None; rate, rrec = rate_for(rates, n, len(hbm.pairs), hbm.cards); mech['rate_model'] = rrec
        bytes_kernel = HN.kernel_bytes_estimate(hbm); mech['bytes'] = dict(witness=W['bytes'], kernel=bytes_kernel, occupation=8 * sum(hbm.cards) * (PROFILE['checkpoints_J'] + 1), peak_admitted=B.peak)
        t0 = tnow(); chain = HN.NativeChain(hbm, x0, a.seed, wclock, budget=B); chain_box[0] = chain; mech['native_build'] = {k: chain.build_record.get(k) for k in ('source_sha256', 'binary_sha256', 'compiler', 'compiler_version', 'library')}
        if a.dev_stream is not None:
            # Stage A development stream: S seconds of native transitions (no publication); the measurement is charged, never production draws
            t1 = tnow(); done = 0
            while tnow() - t1 < a.dev_stream and tnow() < work: done += chain.run(PROFILE['batch_steps'], tag='dev')
            secs = tnow() - t1; c = chain.counters(); mech['dev_stream'] = dict(seconds=secs, steps=done, steps_per_second=(done / secs if secs > 0 else None), fast_path_share=((c['resolved'] / max(1, c['resolved'] + c['exact_fallbacks'])) if done else None), counters=c, bytes_kernel_actual=int(chain.lib.hb_bytes(chain.ctx)))
            # the forecast of the production run at this rate: N_max = rate x (work budget - witness - burn-in time - reserve)
            r_meas = mech['dev_stream']['steps_per_second'] or rate; avail = a.admission_stop - ph['canonicalize'] - ph['witness'] - ph['certificate_setup'] - PROFILE['reserve_s'] - (t_burn / r_meas); N_max = int(max(0.0, avail) * r_meas)
            J = PROFILE['checkpoints_J']; dj = delta_sample / J; plan = MC.checkpoint_plan(N_max, J) if N_max > 0 else []
            mech['forecast'] = dict(steps_per_second_measured=r_meas, available_sampling_s=avail, N_max=N_max, burn_in_steps=t_burn, checkpoints=[dict(N=Nj, radius=float(MC.radius_upper(Nj, out['K'], dj, g))) for Nj in plan], radius_at_N_max=(float(MC.radius_upper(N_max, out['K'], dj, g)) if N_max > 0 else 1.0), completion_N=None)
            # the N needed for completion (radius <= eps) under this delta_j
            lo, hi = 1, 1 << 62
            while lo < hi:
                mid = (lo + hi) // 2
                if MC.radius_upper(mid, out['K'], dj, g) <= eps: hi = mid
                else: lo = mid + 1
            mech['forecast']['completion_N'] = lo; mech['forecast']['completion_seconds_at_rate'] = lo / r_meas
            ph['dev_stream'] = secs; return finish('DEV_STREAM', note='development throughput stream (no publication)')
        # ---- production: burn-in, then the recorded window with the frozen checkpoint plan
        avail = a.admission_stop - (tnow() - t_start) - PROFILE['reserve_s'] - (t_burn / rate); N_max = int(max(0.0, avail) * rate); J = PROFILE['checkpoints_J']; dj = delta_sample / J; plan = MC.checkpoint_plan(N_max, J) if N_max > 0 else []
        mech['checkpoint_plan'] = dict(N_max=N_max, plan=plan, delta_j=str(dj), beta=str(beta), delta_sample=str(delta_sample), rate_steps_per_s=rate, rule=PROFILE['checkpoint_rule'])
        if not plan: mech['refusal'] = dict(kind='ALLOWANCE', reason='no sampling time remains after the witness and the burn-in forecast (%d steps at %.0f steps / s)' % (t_burn, rate)); return finish('REFUSED')
        t1 = tnow(); chain.run(t_burn, tag='burn-in'); ph['burn_in'] = tnow() - t1; chain.set_recording(); t_rec0 = chain.steps(); cps = []; t1 = tnow(); last = None
        for j, Nj in enumerate(plan):
            need = Nj - (chain.steps() - t_rec0)
            if need > 0:
                try: chain.run(need, tag='checkpoint %d' % (j + 1))
                except CE.Refused as e:
                    if getattr(e, 'kind', None) != 'DEADLINE': raise
                    mech['checkpoint_interrupted'] = dict(index=j + 1, reason=str(getattr(e, 'reason', e))[:160], steps_done=chain.steps() - t_rec0); break           # the work clock expired inside a batch: the last COMPLETED checkpoint (if any) publishes
            occ = chain.flush(); N = chain.steps() - t_rec0; assert N == Nj, (N, Nj)
            r = MC.radius_upper(N, out['K'], dj, g); pub, enc, st = MC.rows_from_counts(occ, N, r, eps, M.orig_of, M.fixed_rows)
            snap = dict(index=j + 1, N=N, delta_j=str(dj), radius=float(r), max_width=st['max_width'], published_rows=len(pub), enclosures=len(enc), completed=True, seconds=tnow() - t1, counters=chain.counters()); cps.append(snap); last = (occ, N, r, pub, enc)
            if tnow() >= work: break
        ph['sampling'] = tnow() - t1; mech['checkpoints'] = cps; c = chain.counters(); mech['transitions'] = dict(total=chain.steps(), burn_in=t_burn, recorded=(chain.steps() - t_rec0), native_resolved=c['resolved'], exact_fallbacks=c['exact_fallbacks'], null_moves=c['null_moves'], steps_per_second=((chain.steps()) / max(1e-9, (ph.get('burn_in', 0) + ph['sampling']))))
        if last is None: mech['refusal'] = dict(kind='DEADLINE', reason='no checkpoint completed inside the work allowance'); return finish('DEADLINE')
        occ, N, r, pub, enc = last; t2 = tnow(); rows = []
        for (x, v) in queries:
            if (x, v) in M.fixed_rows: q, gq = M.fixed_rows[(x, v)]; rows.append(dict(var=x, state=v, lo=str(q), hi=str(q), point=str(q), guarantee=gq)); continue
            if (x, v) in pub: lo, hi, p, gg = pub[(x, v)]; rows.append(dict(var=x, state=v, lo=str(lo), hi=str(hi), point=str(p), guarantee=gg))
            else: rows.append(dict(var=x, state=v, guarantee='NOT_PUBLISHED'))
        enc_rows = [dict(var=x, state=v, lo=str(lo), hi=str(hi)) for (x, v, lo, hi) in enc]; ph['publication'] = tnow() - t2
        mech['certificate'] = dict(type='markov_heatbath', N=N, radius=float(r), delta_j=str(dj), beta=str(beta), total_failure_probability=str(beta + delta_sample), worst_radius_on_inventory=float(max([float(F(rw['hi']) - F(rw['lo'])) / 2 for rw in rows if rw['guarantee'] != 'NOT_PUBLISHED'] + [float(F(e['hi']) - F(e['lo'])) / 2 for e in enc_rows] + [0.0])), note='dependent-sample certificate; never mixed with the IID importance certificate')
        return finish('COMPLETE' if all(rw['guarantee'] != 'NOT_PUBLISHED' for rw in rows) else 'PARTIAL', rows, enc_rows)
    except CE.Refused as e:
        mech['refusal'] = dict(kind=e.kind, reason=str(e.reason)[:200]); return finish('DEADLINE' if e.kind == 'DEADLINE' else 'REFUSED')            # CE.Clock.poll raises Refused('DEADLINE'); every other kind is a typed resource refusal
    except Exception as e:
        import traceback; mech['refusal'] = dict(kind='INTERNAL', reason=repr(e)[:200]); mech['traceback'] = traceback.format_exc()[-2000:]; return finish('REFUSED')
    finally:
        if chain_box[0] is not None: chain_box[0].close(); chain_box[0] = None


if __name__ == '__main__': main()
