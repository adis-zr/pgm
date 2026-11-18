"""ITERATION_REPORT.md v2: first screen = hypothesis, identities, THREE verdicts (execution / correctness / coverage), one row per case with TWO labelled evidence channels (A checker-verified;
B sidecar-observed diagnostics with ages); then failures / integrity / not-run, required controls (expected / executed / passed / failed), coverage table, hard kills, costs, limitations, next
question. Timeout rows report what the SIDECAR observed (streams executed; no publication) and a bottleneck only when the phase table covers the elapsed time."""
import json, os
EXACT_ROUTES = ('exact_reference', 'exact_frontier_closure', 'exact_zero_dimensional', 'normalizer_exact_reference', 'normalizer_exact_frontier_closure', 'normalizer_exact_zero_dimensional')
def _cls(c):
    r = c.get('route') or ''
    if c['outcome'] != 'PUBLISHED': return c['outcome']
    if r.startswith('structural'): return 'structural'
    if r in EXACT_ROUTES: return 'exact'
    if 'pac' in r: return 'PAC'
    return 'deterministic-approx'
def _chanA(c):
    a = c.get('activation_verified') or {}; parts = []
    if not a: return '—'
    if a.get('compile_commits'): parts.append('commits %s' % ','.join(a['compile_commits'][:4]))
    if a.get('bias') and any(str(b) not in ('0', 'None') for b in a['bias']): parts.append('bias %s' % ','.join(str(b)[:9] for b in a['bias'][:2]))
    if a.get('ratio_draws'): parts.append('ratio draws %s' % a['ratio_draws'])
    ep = a.get('signed_epochs') or []
    if ep: parts.append('signed epochs %d (draws %d)' % (len(ep), sum(int(e.get('t') or 0) for e in ep)))
    if a.get('frontier'): parts.append('frontier open %s / resolved %s' % (a['frontier'].get('open_cells'), a['frontier'].get('resolved_cells')))
    if a.get('structural'): parts.append('structural %s' % (a['structural'].get('which') or a['structural'].get('route')))
    if a.get('zero_transfer'): parts.append('zero transfer: %s' % str(a['zero_transfer'].get('method'))[:40])
    return '; '.join(parts) or 'verified; no mechanism fields'
def _chanB(c):
    b = c.get('activation_observed')
    if not b: return '—'
    if b.get('error'): return 'sidecar %s' % b['error']
    parts = ['sidecar @%ss' % b.get('elapsed_s_at_write')]
    if b.get('ratio_draws_observed') is not None: parts.append('ratio draws %s (age %s)' % (b['ratio_draws_observed'], b.get('ratio_age_s')))
    if b.get('signed_epochs_observed'): parts.append('signed epochs %d (draws %d)' % (len(b['signed_epochs_observed']), sum(int(e.get('draws') or 0) for e in b['signed_epochs_observed'])))
    if b.get('planner_decisions'): parts.append('planner %s' % '; '.join('%s:%s' % (x[0], x[1]) for x in b['planner_decisions'][-2:]))
    if b.get('phase_at_end'): parts.append('phase %s' % b['phase_at_end'])
    le = b.get('last_enclosure_DIAGNOSTIC')
    if isinstance(le, dict) and le.get('max_width') is not None: parts.append('compiled width max %s (diag)' % str(le['max_width'])[:8])
    return '; '.join(parts)
def _diag(cand, comp, row):
    if cand['status'] == 'NOT_RUN': return 'NOT RUN (%s)' % cand.get('reason', '')
    if cand.get('failure'): return 'FAILURE [%s]: %s' % (cand['failure']['kind'], cand['failure']['msg'])
    co = (comp or {}).get('outcome'); cp = cand['outcome']; pr = cand.get('predicates') or {}
    cov = ', '.join('%s %s' % (p, 'ACTIVE' if pr.get(p) else 'NOT exercised') for p in (row.get('coverage_required') or [])) or 'none required'
    if comp is None: v = 'control: %s' % cp
    elif cp in ('PUBLISHED', 'PROVED_ZERO_EVIDENCE') and co not in ('PUBLISHED', 'PROVED_ZERO_EVIDENCE'): v = 'candidate resolves where the comparator does not'
    elif cp not in ('PUBLISHED', 'PROVED_ZERO_EVIDENCE') and co in ('PUBLISHED', 'PROVED_ZERO_EVIDENCE'): v = 'REGRESSION / LOSS vs comparator'
    elif cp == co == 'PUBLISHED':
        wc, wo = cand.get('wall_s') or 0, comp.get('wall_s') or 0; v = 'both publish; wall ratio cand/comp %.2f' % (wc / wo) if wo else 'both publish'
    else:
        b = cand.get('activation_observed') or {}; obs = []
        if b.get('ratio_draws_observed'): obs.append('ratio stream executed (%s draws observed)' % b['ratio_draws_observed'])
        if b.get('signed_epochs_observed'): obs.append('signed stream executed (%d epochs observed)' % len(b['signed_epochs_observed']))
        if b.get('planner_decisions'): obs.append('planner: ' + '; '.join('%s %s%s' % (x[0], x[1], (' (' + x[2] + ')') if x[2] else '') for x in b['planner_decisions'][-2:]))
        pt = b.get('phase_times_s') or {}; cov_s = b.get('phase_table_covers_s') or 0; el = cand.get('wall_s') or 0
        if pt and el and cov_s >= 0.8 * el: obs.append('dominant phase %s (%.2fs of %.2fs)' % (max(pt.items(), key=lambda kv: kv[1])[0], max(pt.values()), el))
        elif pt: obs.append('phase table covers %.2fs of %.2fs: no dominant-phase claim' % (cov_s, el))
        v = 'both %s / %s; no publication; ' % (cp, co) + ('; '.join(obs) if obs else 'UNKNOWN cause (no sidecar observation retained)')
    return v + '; coverage: ' + cov
def write_md(rec, rows, path):
    h = rec.get('hypothesis') or {}; ids = rec.get('identities') or {}
    L = ['# CQR fast-loop iteration report %s' % (('— ' + rec['label']) if rec.get('label') else ''), '', '**Status: %s** — execution **%s** · correctness **%s** · required coverage **%s** (elapsed %s s of the %.0f s cap%s)%s' % (rec['status'], rec['execution'], rec['correctness'], rec['coverage'], rec.get('elapsed_s'), rec['cap_s'], '' if rec.get('within_cap') in (True, None) else '; CAP EXCEEDED', ('. ' + rec['stop_reason']) if rec.get('stop_reason') else ''), '']
    if rec.get('harness_exception'): L += ['**HARNESS EXCEPTION:** %s: %s' % (rec['harness_exception']['type'], rec['harness_exception']['msg']), '']
    L += ['## Hypothesis (preregistered)', '', '* **Change:** %s' % h.get('change'), '* **Mathematical premise:** %s' % h.get('premise'), '* **Expected favorable behaviour:** %s' % h.get('expected_favorable'), '* **Expected near-miss behaviour:** %s' % h.get('expected_near_miss'), '* **Preserved capabilities:** %s' % '; '.join(h.get('preserved') or []), '']
    L += ['## Identities', '', '| build | git head | cqr scope | full inventory | clean |', '|---|---|---|---|---|']
    for k in ('candidate', 'baseline'):
        i = ids.get(k) or {}; L.append('| %s (`%s`) | %s | %s | %s (%s) | %s |' % (k, i.get('build'), str(i.get('git_head'))[:12], str(i.get('cqr_scope_sha256'))[:12], str(i.get('full_inventory_sha256'))[:12], i.get('artifacts'), i.get('tracked_clean')))
    pl = rec.get('plan') or {}; L += ['', 'Manifest %s; oracle identity %s; harness %s; mode %s; worker nominal %s s (cap %s s); finalization reserve %.0f s.' % (str(rec.get('manifest_sha256'))[:12], str((ids.get('oracle') or {}).get('sha256'))[:12], rec['harness'], pl.get('mode'), pl.get('worker_nominal_s'), (pl.get('allocations') or {}).get('worker_nominal_s_cap'), rec['finalization_reserve_s']), '']
    L += ['## Cases', '', '| case / purpose | comparator → candidate | class | A: checker-verified facts | B: sidecar observations (diagnostic) | truth / checker | wall (comp → cand) | diagnosis |', '|---|---|---|---|---|---|---|---|']
    by = {}
    for c in rec['cells']: by.setdefault(c['id'], {})[c['tag']] = c
    for r in rows:
        cs = by.get(r['id'], {}); cand = cs.get('candidate'); comp = cs.get('comparator')
        if cand is None: L.append('| %s | NOT RUN | | | | | | |' % r['id']); continue
        ck = cand.get('check') or {}; tr = cand.get('truth') or {}
        L.append('| %s<br>_%s_ | %s → **%s** | %s | %s | %s | %s / %s | %s → %s | %s |' % (r['id'], r['block'], ('%s (%s%s)' % (comp['outcome'], comp['arm'], (' ' + comp.get('route')) if comp.get('route') else '')) if comp else '— (control)', '%s%s' % (cand['outcome'], (' ' + cand['route']) if cand.get('route') else ''), _cls(cand), _chanA(cand), _chanB(cand), '%s%s' % (tr.get('verdict', tr.get('status')), (' (%s)' % tr.get('method')) if tr.get('method') else ''), ck.get('status', '—'), ('%.2fs' % comp['wall_s']) if comp else '—', '%.2fs' % (cand.get('wall_s') or 0), _diag(cand, comp, r)))
    reg = [c for c in rec['cells'] if c['tag'] == 'candidate' and c['outcome'] not in ('PUBLISHED', 'PROVED_ZERO_EVIDENCE') and (by[c['id']].get('comparator') or {}).get('outcome') in ('PUBLISHED', 'PROVED_ZERO_EVIDENCE') and (by[c['id']].get('comparator') or {}).get('comparator_kind') == 'baseline_N1']
    L += ['', '## Regressions vs the accepted baseline', ''] + (['* **%s**: candidate %s, baseline %s' % (c['id'], c['outcome'], by[c['id']]['comparator']['outcome']) for c in reg] or ['none observed on this panel'])
    L += ['', '## Failures, integrity, incomplete and skipped', ''] + ['* HARD [%s] %s: %s' % (x['kind'], x['where'], x['msg']) for x in rec['hard_failures']] + ['* INTEGRITY %s %s: fields %s' % (x['kind'], x['id'], x['fields']) for x in rec['integrity_failures']] + ['* NOT RUN: %s / %s: %s' % tuple(x) for x in rec['not_run']] + ['* NO OUTPUT: %s / %s: %s' % tuple(x) for x in rec['no_output']] + ['* UNVERIFIED: %s / %s (%s)' % tuple(x) for x in rec['unverified']] + ['* UNVERIFIABLE: %s / %s: %s' % tuple(x) for x in rec.get('unverifiable') or []] + (['none'] if not (rec['hard_failures'] or rec['integrity_failures'] or rec['not_run'] or rec['no_output'] or rec['unverified'] or rec.get('unverifiable')) else [])
    rc = rec['required_controls']; L += ['', '## Required negative controls (copies; the checker must COMPLETE and REFUSE for the intended class)', '', 'expected %d · executed %d · passed %d · failed %d · missing %s' % (len(rc['expected']), len(rc['executed']), len(rc['passed']), len(rc['failed']), rc.get('missing') or []), ''] + ['* %s: **%s** (checker %s, completed %s) — %s' % (m['name'], m['status'], m.get('checker_status'), m.get('checker_completed'), m.get('first') or m.get('reason')) for m in rec['mutation_controls']]
    L += ['', '## Required capability coverage (predicates from checker-verified facts)', ''] + (['* %s: %s' % (x['id'], ', '.join(x['predicates'])) for x in rec['coverage_required']] or ['none required by the manifest']) + (['', 'MISSING: ' + '; '.join('%s:%s (observed %s %s)' % (x['id'], x['predicate'], x['observed'], x.get('route') or '') for x in rec['coverage_missing'])] if rec['coverage_missing'] else ['', 'all required predicates ACTIVE'] if rec['coverage_required'] else [])
    L += ['', '## Hard kills / supervisor', ''] + (['* %s / %s: %s survivors=%s' % (c['id'], c['tag'], c['status'], (c.get('supervisor') or {}).get('survivors')) for c in rec['cells'] if c.get('status') in ('TIMEOUT_KILL', 'MEMORY_KILL') or (c.get('supervisor') or {}).get('survivors')] or ['none'])
    ch = rec.get('charges') or {}; L += ['', '## Costs', '', '* run elapsed %s s (measured AFTER finalization); %s supervised cell receipts, %s s charged inside them (nested inside the outer receipt when launched through gbidi.supervise); host %s load %.1f' % (rec.get('elapsed_s'), ch.get('cell_receipts'), ch.get('cell_wall_s'), rec['host']['node'], rec['host']['load_avg_1m']), '* every cell: `cells/<n>_<id>__<tag>__<arm>/` (worker.json, worker.diag.json, check.json, stdout / stderr); inputs snapshotted under `inputs/<id>/`']
    L += ['', '## Limitations', ''] + ['* ' + x for x in rec['limitations']]
    L += ['', '## Next question', '', h.get('question') or 'Which step of the hypothesis failed? activation (channel A) → benefit (truth / wall) → bottleneck (channel B) → regression.']
    open(path, 'w').write('\n'.join(L) + '\n')
