"""UNIFIED_SCHEDULING_REVISION_1 calibration (brief section 5): the frozen 32-model development panel, one fresh measurement process per model, and the single NNLS fit of the R1 cost model.
  gen OUTDIR                      -- 30 models = hp_gen.build / permute (UNCHANGED) under tag UNIFIED-SCHEDULING-CALIBRATION-1 over topology {cycle16, grid4x4} x card {2,4,8,16,32} x family
                                      {exact, perturbed, generic} in that lexicographic loop order, + 2 calibrate_unified.dev_model models (6001, 6, 2, cycle, exact), (6002, 6, 4, grid, generic); hashes in GENERATED_MANIFEST.json
  measure MODEL.uai OUT.json      -- ONE process: 1.85 s hard worker cutoff, 1.75 s action-work cutoff, each native call min(0.60 s, remaining work); fixed order: canonicalize / price identity; identity
                                      solve + recovery; exact quotient (+ solve if nonaliased); FAST on identity (+ lower; + upper if nonexact with a positive lower witness); one refinement of it (not solved);
                                      FAST on a nontrivial exact parent (+ lower; + upper likewise). Identical native model / order / query executions are NOT re-dispatched (semantic key over cards, evidence, order, every scope + exact value stream): the earlier result is reused and only the recovery is timed (recorded as recovery_only). Completed phases are kept before a later deadline.
  fit MEASURE_DIR RATES_OUT.json RECORD_OUT.json -- one unweighted NNLS fit per block over the COMPLETED measurements (censored ones retained, excluded); minimum-coverage checks; writes the frozen R1 file."""

# Source-checkout entry point; production imports never traverse research.
if __package__ in (None, ""):
    import sys as _research_sys
    from pathlib import Path as _ResearchPath
    _research_sys.path.insert(0, str(_ResearchPath(__file__).resolve().parents[3]))
from research.bootstrap import activate as _activate_research
_activate_research()
from research.paths import repo_root as _repo_root, runs_root as _runs_root, records_root as _records_root, source_path as _source_path
import sys, os, json, time, hashlib, argparse, math
from fractions import Fraction as F
HERE = os.path.dirname(os.path.abspath(__file__))
TAG = 'UNIFIED-SCHEDULING-CALIBRATION-1'; HARD_S = 1.85; WORK_S = 1.75; NATIVE_CAP_S = 0.60


def gen(outdir):
    import research.campaigns.hp.hp_gen as G, research.campaigns.hp.calibrate_unified as CU
    os.makedirs(outdir, exist_ok=True); man = []
    for topo in ('cycle16', 'grid4x4'):
        for card in (2, 4, 8, 16, 32):
            for fam in ('exact', 'perturbed', 'generic'):
                m0, rec = G.build(TAG, topo, card, fam); m, pi = G.permute(TAG, topo, card, fam, m0); name = 'cal_%s_c%d_%s' % (topo, card, fam); p = os.path.join(outdir, name + '.uai'); G.write(p, m)
                man.append(dict(name=name, recipe='hp_gen.build/permute', tag=TAG, topology=topo, card=card, family=fam, model=os.path.abspath(p), model_sha256=hashlib.sha256(open(p, 'rb').read()).hexdigest(), nvars=len(m['cards']), entries=sum(len(f['values']) for f in m['factors'])))
    for seed, n, card, topo, fam in ((6001, 6, 2, 'cycle', 'exact'), (6002, 6, 4, 'grid', 'generic')):
        m = CU.dev_model(seed, n, card, topo, fam); name = 'cal_dev_%d_%s_c%d_%s' % (seed, topo, card, fam); p = os.path.join(outdir, name + '.uai'); G.write(p, m)
        man.append(dict(name=name, recipe='calibrate_unified.dev_model(%d, %d, %d, %s, %s)' % (seed, n, card, topo, fam), topology=topo, card=card, family=fam, model=os.path.abspath(p), model_sha256=hashlib.sha256(open(p, 'rb').read()).hexdigest(), nvars=n, entries=sum(len(f['values']) for f in m['factors'])))
    json.dump(dict(tag=TAG, generator_sha256=hashlib.sha256(open(__file__, 'rb').read()).hexdigest(), hp_gen_sha256=hashlib.sha256(open(os.path.join(HERE, 'hp_gen.py'), 'rb').read()).hexdigest(), inputs=man, note='family labels / latent maps are NOT planner inputs or cost features'), open(os.path.join(outdir, 'GENERATED_MANIFEST.json'), 'w'), indent=1)
    return man


def measure(model_path, out_path):
    import pgm.algorithms.quotient.unified_planner as UP, pgm.algorithms.quotient.coarse_envelope as CE, pgm.algorithms.structural.core as CORE
    t_start = UP.T_PROCESS_START; hard = t_start + HARD_S; adm = t_start + WORK_S
    t0 = UP.tnow(); model, binding = CORE.read_uai(model_path); tread = UP.tnow() - t0
    P = UP.Planner(model, HARD_S, admission_stop_s=WORK_S, t_start=t_start, policy='unified', sched='P0', rates='R0'); out = P.out; out['binding'] = binding; out['input'] = os.path.abspath(model_path); out['phases_s']['read'] = tread; out['calibration_driver'] = dict(hard_s=HARD_S, work_s=WORK_S, native_cap_s=NATIVE_CAP_S, order=['identity', 'exact', 'fast(identity)', 'refine', 'fast(exact)'])
    def native_deadline(): return min(adm, UP.tnow() + NATIVE_CAP_S)
    seen = {}; out['dedup'] = dict(skipped=[], dispatched=0)
    def native_key(c, side):
        import hashlib
        cm = P.exec_model(c, 0 if side == 'lower' else 1); h = hashlib.sha256(json.dumps([list(cm['cards']), sorted(cm['evidence'].items()), list(c.order), [[list(f['scope']), [str(x) for x in f['values']]] for f in cm['factors']]]).encode()).hexdigest(); return h
    def solve(c, side):
        if UP.tnow() >= adm: return None
        k = native_key(c, side)
        if k in seen:                                                                        # identical native model / order / query already executed in this fixture: reuse its result for recovery, do not re-dispatch the native call
            prev = seen[k]; out['dedup']['skipped'].append(dict(cand=c.name, side=side, same_as=prev.name, key=k[:16]))
            if side == 'lower': c.SL = prev.SL if prev.SL is not None else prev.SU
            else: c.SU = prev.SU if prev.SU is not None else prev.SL
            if (c.SL if side == 'lower' else c.SU) is None: return None
            P.out['mechanism']['positive_mass_witness'] = True; t_r = UP.tnow()
            try: rows, pub = P.recover(c, UP.Clock(adm, P.stats)); c.status[side] = 'SOLVED_REUSED_NATIVE'; P.measurements.append(dict(kind='recovery_only', cand=c.name, side=side, features=P.solve_features(c, 0 if side == 'lower' else 1), recovery_s=UP.tnow() - t_r, completed=True, reused_native_of=prev.name))
            except UP.Refused as e: P.measurements.append(dict(kind='recovery_only', cand=c.name, side=side, features=P.solve_features(c, 0 if side == 'lower' else 1), recovery_s=UP.tnow() - t_r, completed=False, censored=e.kind, reused_native_of=prev.name))
            return None
        seen[k] = c; out['dedup']['dispatched'] += 1
        return P.perform(dict(kind='solve', cand=c, side=side, deadline=native_deadline(), record=dict(T_b_s=None)))
    def construct(name, cand):
        if UP.tnow() >= adm: return None
        before = set(id(x) for x in P.cands); P.perform(dict(kind='optional', act=dict(name=name, cand=cand, D=0.0, S=0.0, parts={}), deadline=adm, record={}))
        new = [x for x in P.cands if id(x) not in before]; return new[-1] if new else None
    try:
        P.hclock.poll('entry'); t1 = UP.tnow(); P.M = M = CE.canonicalize(model, P.clock, P.budget); out['phases_s']['canonicalize'] = UP.tnow() - t1; P.canonical_charge = P.budget.live
        if M.zero_mass or not M.cards: out['calibration_note'] = 'degenerate model (zero mass or no retained variables): no measurements'; return finish(P, out, out_path, hard)
        t2 = UP.tnow(); P.mf = UP.CM.model_features(M, P.clock, P.budget); out['phases_s']['features'] = UP.tnow() - t2; out['mechanism']['features'] = dict(P.mf)
        t3 = UP.tnow(); ident = P.make_identity(P.clock); P.cands.append(ident); out['phases_s']['price_identity'] = UP.tnow() - t3
        solve(ident, 'lower')
        ex = construct('discover_exact', None)
        if ex is not None and not ex.alias_of: solve(ex, 'lower')
        fa = construct('discover_fast', ident)
        if fa is not None:
            solve(fa, 'lower')
            if fa.SL is not None and not fa.SL.zero and not fa.exact: solve(fa, 'upper')
            if fa.SL is not None and not fa.SL.zero: construct('refine', fa)
        if ex is not None and not ex.alias_of:
            P.n_fast_disc = 0; fe = construct('discover_fast', ex)                                  # the driver may exercise both parents (production keeps the single FAST cap)
            if fe is not None:
                solve(fe, 'lower')
                if fe.SL is not None and not fe.SL.zero and not fe.exact: solve(fe, 'upper')
    except UP.Refused as e: out['mechanism']['refusal'] = dict(kind=e.kind, reason=str(e.reason)[:200])
    except UP.Defect as e: out['mechanism']['defect'] = str(e)[:200]
    return finish(P, out, out_path, hard)


def finish(P, out, out_path, hard):
    import pgm.algorithms.quotient.unified_planner as UP
    rows = UP.CE.publish(P.M, P.retained, P.eps, P.hclock) if (P.M is not None and P.retained) else {}
    res = P.fin('PARTIAL' if any(rows.values()) else 'REFUSED', rows, note='calibration driver: measurements only'); res['measurements'] = P.measurements
    res = UP.write_result(res, out_path, HARD_S); fa = res['phases_s'].get('final_assembly', 0.0); ow = res['phases_s'].get('output', 0.0)
    res['measurements'].append(dict(kind='final', features=dict(J=len(P.inventory)), seconds=fa + ow, final_assembly_s=fa, output_s=ow, completed=res.get('hard_deadline_respected_at_commit', False)))
    json.dump(res, open(out_path, 'w'), indent=1, default=str); print(json.dumps(dict(outcome=res['outcome'], measurements=[(m['kind'], m.get('completed'), round(m.get('seconds', m.get('native_total_s', 0)), 4)) for m in res['measurements']], wall=round(res['wall_s'], 3)), default=str)); return res


def collect(measure_dir):
    """completed measurements by block; censored ones listed separately"""
    import pgm.algorithms.quotient.cost_model as CM
    rows = {b: [] for b in CM.BLOCKS}; censored = []; per_file = []
    for f in sorted(os.listdir(measure_dir)):
        if not f.endswith('.json') or f.startswith('GENERATED'): continue
        d = json.load(open(os.path.join(measure_dir, f)))
        for m in d.get('measurements', []):
            if not m.get('completed'): censored.append(dict(file=f, kind=m['kind'], censored=m.get('censored'), seconds=m.get('seconds', m.get('native_total_s')))); continue
            if m['kind'] == 'native':
                fs = m['features']; rows['native_host'].append((fs, m['host_s'], f)); rows['native_kernel'].append((fs, m['kernel_s'], f))
                if m.get('recovery_completed', True) and m.get('recovery_s') is not None: rows['recovery'].append((fs, m['recovery_s'], f))
                elif m.get('recovery_s') is not None: censored.append(dict(file=f, kind='recovery', censored=m.get('recovery_censored'), seconds=m['recovery_s']))
                if m.get('host_negative_raw'): censored.append(dict(file=f, kind='native_host', censored='NEGATIVE_RAW_INSTRUMENTATION', seconds=m['host_s']))
            elif m['kind'] == 'recovery_only': rows['recovery'].append((m['features'], m['recovery_s'], f))
            elif m['kind'] in ('exact_construction', 'fast_construction', 'refine_construction', 'final'): rows[m['kind']].append((m['features'], m['seconds'], f))
        per_file.append(dict(file=f, outcome=d.get('outcome'), wall_s=d.get('wall_s'), n_measurements=len(d.get('measurements', []))))
    return rows, censored, per_file


def fit(measure_dir, rates_out, record_out, source_identity=None):
    import pgm.algorithms.quotient.cost_model as CM
    rows, censored, per_file = collect(measure_dir); blocks = {}; incomplete = []
    for b in CM.BLOCKS:
        data = [(f, s) for f, s, _ in rows[b]]; vecs = {tuple(CM.regressors(b, f)) for f, _ in data}; nz = {v for v in vecs if any(x != 0 for x in v)}
        if len(data) <= len(CM.BLOCKS[b]) + 1 or len(nz) < 2: incomplete.append(dict(block=b, n=len(data), distinct_nonzero_vectors=len(nz), need_more_than=len(CM.BLOCKS[b]) + 1)); continue
        r = CM.fit_nnls(data, b)
        if not all(math.isfinite(x) for x in [r['intercept']] + r['coefficients']): incomplete.append(dict(block=b, reason='nonfinite fit')); continue
        r['files'] = [x[2] for x in rows[b]]; blocks[b] = r
    cov = dict(identity_card16_grid=any('c16' in x[2] and 'grid' in x[2] for x in rows['native_host']), identity_card32_cycle=any('c32' in x[2] and 'cycle' in x[2] for x in rows['native_host']), recovery_h0=any(f['h'] == 0 for f, _, _ in rows['recovery']), recovery_h1=any(f['h'] == 1 for f, _, _ in rows['recovery']), recovery_h2=any(f['h'] >= 2 for f, _, _ in rows['recovery']), recovery_upper=any(f.get('U', 0) > 0 for f, _, _ in rows['recovery']))
    status = 'FITTED' if not incomplete and all(cov.values()) else 'CALIBRATION_INCOMPLETE'
    rates = dict(model='R1 nonnegative affine per block over fixed physical work counts (cost_model.py)', status=status, frozen=(status == 'FITTED'), fitted_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), tag=TAG, blocks={b: dict(intercept=r['intercept'], coefficients=r['coefficients'], regressors=r['regressors'], n=r['n'], rank_deficient=r['rank_deficient'], dropped_all_zero=r['dropped_all_zero']) for b, r in blocks.items()}, incomplete=incomplete, coverage=cov, source_identity=source_identity or {})
    rates['sha256'] = hashlib.sha256(json.dumps({k: v for k, v in rates.items() if k != 'sha256'}, sort_keys=True, default=str).encode()).hexdigest()
    json.dump(rates, open(rates_out, 'w'), indent=1); json.dump(dict(rates=rates, fits=blocks, censored=censored, per_file=per_file, n_completed_by_block={b: len(rows[b]) for b in CM.BLOCKS}), open(record_out, 'w'), indent=1, default=str)
    print(json.dumps(dict(status=status, n_by_block={b: len(rows[b]) for b in CM.BLOCKS}, coverage=cov, incomplete=incomplete, censored=len(censored)))); return rates


if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('cmd', choices=['gen', 'measure', 'fit']); ap.add_argument('args', nargs='*'); ap.add_argument('--source-identity', default=None); a = ap.parse_args()
    if a.cmd == 'gen': [print(m['name'], m['entries'], m['model_sha256'][:12]) for m in gen(a.args[0])]
    elif a.cmd == 'measure': measure(a.args[0], a.args[1])
    else: fit(a.args[0], a.args[1], a.args[2], json.load(open(a.source_identity)) if a.source_identity else None)
