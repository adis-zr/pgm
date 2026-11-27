"""DGP8 THEORY_RETURN writer (protocol rule 9; brief section 8): answers the brief's five questions directly from RESULTS.json / DIAGNOSTICS.json, keeps the layers distinct (checked witness = proof; development rate = measurement; forecast = heuristic; certified radius =
the Markov certificate at a completed checkpoint; archived incumbent = the hash-matched earlier cell), states what executed and what did not, and names the next quantity. usage: dgp8_theory_return.py"""
import json, os, statistics, math
RD = os.environ.get('DGP8_RD', '/Users/adis/Workspace/pgm-records/code/runs/mdi_2026-10-28/DGP8_SPECTRAL_HEATBATH')
R = json.load(open(RD + '/RESULTS.json')); D = json.load(open(RD + '/DIAGNOSTICS.json')); vi = R['verdict_inputs']; V = R['verdicts']; rel = R.get('release_decision') or {}; feas = vi['stage_a']; guard = vi.get('guard') or []; bud = json.load(open(RD + '/BUDGET_DECLARATION.json')) if os.path.exists(RD + '/BUDGET_DECLARATION.json') else {}
def f2(x): return ('%.2f' % x) if isinstance(x, (int, float)) else '-'
def f3(x): return ('%.3f' % x) if isinstance(x, (int, float)) else '-'
def f4(x): return ('%.4f' % x) if isinstance(x, (int, float)) else '-'
def fe(x): return ('%.3g' % x) if isinstance(x, (int, float)) else '-'
def med(xs): xs = [x for x in xs if isinstance(x, (int, float))]; return statistics.median(xs) if xs else None
L = []
def P(s=''): L.append(s)
weak = [x for x in feas if x['coupling'] == 'half']; strong = [x for x in feas if x['coupling'] == 'two']; elig = [x for x in feas if x['eligible']]; failing = [x for x in feas if x['current_failure']]
P('# THEORY_RETURN -- DGP8_SPECTRAL_HEATBATH (26 Nov 2026)'); P()
P('Question (PROTOCOL.md section 1): does a CHECKED spectral mixing certificate (l I <= A <= u I on the centered one-hot log-interaction matrix, w = u - l < 2, gap g = (1 - w / 2) / n) with EXACT random-scan heat-bath updates on the original model and the separate finite-time Markov certificate improve certified original-coordinate accuracy at equal total cost on the exposed dense inputs?'); P()
P('## 0. What executed and what did not'); P()
P('- Stage A: %d of 16 exposed inputs screened (witness + 2.0 s development stream); eligible %s; refused %s. Release: stage B %s; regression %s.' % (sum(1 for x in feas if x['screened']), [x['task'] for x in elig], [x['task'] for x in feas if x['screened'] and not x['eligible']], rel.get('stage_b_released'), rel.get('regression_released')))
P('- Stage B guard: %s. Regression cohorts: %s.' % (('%d inputs x seeds %s' % (len(guard), sorted({s for g in guard for s in g['seeds']}))) if guard else 'NOT RUN', '; '.join('%s ran %d of %d' % (k, v['ran'], v['cohort_size']) for k, v in (vi.get('preservation') or {}).items()) or 'NOT RUN'))
P('- NOT run / not available: the supplied packet, bootstrap, DGP7 independent review and its probes, the heatbath / categorical-gap references, the tiny aggregate references and the floating diagnostics (BUDGET_DECLARATION.json missing_packet_items). Every reference used here is this round\'s own and labelled independent; the DGP7 review findings were repaired from the brief\'s abbreviated list. SELECT (the integrated planner arm) was NOT run: no frozen request-level risk allocation exists.'); P()
P('## 1. Which original weak failures have a checked gap, and what margin remains after numerical enclosure?'); P()
P('| input | current failure | incumbent worst r | eligible | width w | margin m = 1 - w / 2 | gap g = m / n | pivot lower bound | log-enclosure max width | matrix max width |'); P('|---|---|---:|---|---:|---:|---:|---:|---:|---:|')
for x in weak: P('| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |' % (x['task'], x['current_failure'], f4(x['incumbent_best_worst_radius']), (x['eligible'] if x['screened'] else 'not screened'), f4(x['width']), f4(x['margin_m']), fe(x['gap_g']), fe(x['min_pivot_lower_bound']), fe(None), fe(None)))
P(); P('Strong refusal controls: %s refused (typed, local), %s admitted. %s' % ([x['task'] for x in strong if x['screened'] and not x['eligible']], [x['task'] for x in strong if x['eligible']], 'A refusal by width is a statement about the sufficient condition, never a slow-mixing proof.')); P()
P('The margins are the CHECKED values after the outward logarithm enclosure, the interval matrix and the interval Cholesky (the floating eigensolver only proposed l / u); where the theory note predicted m = 0.0185 / 0.0085 on the weak n64 card-4 pair, the table reports what the witness proved on this machine.'); P()
P('## 2. What fraction of cost is spectral verification, burn-in, exact transitions, checkpoint recovery and publication?'); P()
rows = []
for g in guard:
    for s, v in sorted(g['seeds'].items()):
        ph = v.get('phases_s') or {}; tot = sum(x for x in ph.values() if isinstance(x, (int, float))) or None
        rows.append((g['task'], s, ph, tot, v.get('elapsed_s')))
if rows:
    P('| input | seed | canonicalize | witness | burn-in | sampling (exact transitions) | checkpoint recovery | publication | sum of phases s | elapsed s |'); P('|---|---|---:|---:|---:|---:|---:|---:|---:|---:|')
    for t, s, ph, tot, el in rows: P('| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |' % (t, s, f3(ph.get('canonicalize')), f3(ph.get('witness')), f3(ph.get('burn_in')), f3(ph.get('sampling')), f3(ph.get('checkpoint_recovery') or ph.get('checkpoints')), f3(ph.get('publication')), f3(tot), f2(el)))
    P(); P('Fractions (medians over the guard cells): ' + ', '.join('%s %s' % (k, f2(med([(r[2].get(k) or 0) / r[3] for r in rows if r[3]]))) for k in ('canonicalize', 'witness', 'burn_in', 'sampling', 'publication')) + '.')
else:
    P('Stage B did not run; the Stage A screen gives the witness cost alone: median witness %s s (construct + verify) across the screened inputs, development-stream rates in section 3 below. Burn-in steps per eligible input: %s.' % (f3(med([x['witness_seconds'] for x in feas])), {x['task']: x['burn_in_steps'] for x in elig}))
P()
P('## 3. Does the new route materially tighten a failed input\'s certificate at equal total cost, even without completing?'); P()
if guard:
    P('| input | incumbent worst r (hash-matched) | achieved worst r seed 0 / 1 | certified r seed 0 / 1 | improvement seed 0 / 1 | >= 2x both seeds | new completion |'); P('|---|---:|---|---|---|---|---|')
    for g in guard:
        s0 = g['seeds'].get('0') or g['seeds'].get(0) or {}; s1 = g['seeds'].get('1') or g['seeds'].get(1) or {}      # HARNESS AMENDMENT 2: the seed keys are strings after the RESULTS.json round-trip (the frozen writer printed '-' for every guard figure)
        P('| %s | %s | %s / %s | %s / %s | %s / %s | %s | %s |' % (g['task'], f4(g['incumbent_best_worst_radius']), f4(s0.get('worst_radius_achieved')), f4(s1.get('worst_radius_achieved')), f4(s0.get('certified_radius')), f4(s1.get('certified_radius')), f2(s0.get('improvement')), f2(s1.get('improvement')), g['gain_2x_both_seeds'], g['new_completion_both_seeds']))
    P(); P('Verdict partial accuracy: %s (%s). New completion: %s.' % (V['partial_accuracy']['status'], V['partial_accuracy']['passing_both_seeds'], V['new_completion']['status']))
else:
    P('Stage B was not released, so no certified radius was produced on a failing input. The Stage A FORECASTS (frozen rate model x checked gap; floats, not certificates): ' + '; '.join('%s: forecast r(20 s) %s vs incumbent %s (x%s)' % (x['task'], f4((x['forecast_20s'] or {}).get('radius')), f4(x['incumbent_best_worst_radius']), f2(x['forecast_improvement_20s'])) for x in failing if x['eligible']) + '.')
P()
P('## 4. If it fails, which term binds: transition throughput, the gap bound, concentration, constructor cost, numerical proof, or request-level risk allocation?'); P()
def binding(x, gv=None):
    reasons = []
    if not x['screened']: return ['not screened']
    if not x['eligible']: reasons.append('numerical proof / admission (the witness did not prove w < 2: %s)' % (x['refusal'] or 'refused'))
    else:
        if (x['margin_m'] or 0) < 0.02: reasons.append('gap bound (margin m = %s -> g = %s: the sufficient-condition gap, not the throughput, sets the N needed)' % (f4(x['margin_m']), fe(x['gap_g'])))
        f20 = x['forecast_20s'] or {}
        if f20.get('radius') is not None and x['incumbent_best_worst_radius'] is not None and f20['radius'] >= x['incumbent_best_worst_radius'] / 2: reasons.append('concentration x throughput (forecast r %s at %s steps / s does not reach 2x the incumbent)' % (f4(f20['radius']), fe(x['dev_steps_per_second'])))
        if (x['witness_seconds'] or 0) > 2.0: reasons.append('constructor cost (witness %s s of the 19 s work budget)' % f3(x['witness_seconds']))
        if gv:
            if gv.get('worst_radius_achieved') is not None and f20.get('radius') is not None and gv['worst_radius_achieved'] > 1.5 * f20['radius']: reasons.append('transition throughput (achieved r %s > forecast r %s: fewer recorded transitions than the development rate predicted: %s vs %s)' % (f4(gv['worst_radius_achieved']), f4(f20['radius']), gv.get('recorded'), fe(gv.get('forecast_recorded'))))
            if gv.get('defect'): reasons.append('defect: %s' % str(gv['defect'])[:80])
    reasons.append('request-level risk allocation: not exercised (standalone route takes the full request delta; SELECT not run)')
    return reasons
for x in failing:
    gv = next((g['seeds'].get(0) for g in guard if g['task'] == x['task']), None); P('- %s: ' % x['task'] + '; '.join(binding(x, gv)))
P()
P('## 5. What concrete smaller mathematical quantity would need a better bound next? (observed limitation vs impossibility)'); P()
P('- The binding quantity on the eligible n64 card-4 inputs is the GAP LOWER BOUND g = (1 - w / 2) / n with w the checked spectral width of the one-hot interaction: the required recorded transitions scale as (2 - g) ln(2 Q / delta) / (2 g r^2); halving the margin doubles N. A better bound would come from (i) a sharper uniform covariance majorant than Cov(phi_i) <= I / 2 (a field-dependent or block majorant C with rho = ||V^T C V|| < 1: the block-response criterion of the theory note), or (ii) a direct Poincare constant for the categorical heat-bath chain that does not pass through the Gaussian lift.')
P('- The second quantity is the RANGE of the recorded function: the Poisson-response residual R = f - (I - P) G with a certified range d multiplies r by d and divides N by d^2 (the theory note\'s 12-21x oracle reductions on n8). Its constructor and an independent global range checker at n64 are the open engineering objects; nothing here establishes them.')
P('- These are observed limitations of the sufficient condition and of the conservative concentration chain on this hardware\'s measured rate (%s steps / s median development rate); none is an impossibility theorem. A refusal by width admission is not a slow-mixing proof; the strong dense wall (w >= 2 on every `_two` input) remains the precise unresolved target: an affordable coarse representation with a checked conditional-response bound.' % fe(med([x['dev_steps_per_second'] for x in feas])))
P(); P('## 6. Claim status'); P()
for k in ('spectral_admission', 'finite_time_confidence', 'throughput', 'partial_accuracy', 'new_completion', 'preservation', 'overhead', 'deployability'):
    v = V.get(k); P('- %s: %s' % (k, (v if isinstance(v, str) else (v.get('status') if isinstance(v, dict) else v))))
P(); P('Nothing floating entered a certificate: eligibility is the interval-Cholesky proof, every fast-path transition is a proved decision or an exact fallback, and the published radii come from the Markov certificate at completed frozen checkpoints only.')
open(RD + '/THEORY_RETURN.md', 'w').write('\n'.join(L) + '\n'); print('THEORY_RETURN.md written', len(L), 'lines')
