"""ITERATION_REPORT.md: the first screen = hypothesis, identities, status, one row per case (comparator -> candidate outcome, verified route + activation, truth / checker, wall,
approximation progress, diagnosis); then regressions / failures / skipped / controls / limitations; ends with the next justified question. Never a PASS count."""
import json, os
EXACT_ROUTES = ('exact_reference', 'exact_frontier_closure', 'exact_zero_dimensional', 'normalizer_exact_reference', 'normalizer_exact_frontier_closure', 'normalizer_exact_zero_dimensional')
def _route_class(c):
    r = c.get('route') or ''
    if c['outcome'] != 'PUBLISHED': return c['outcome']
    if r.startswith('structural'): return 'structural'
    if r in EXACT_ROUTES: return 'exact'
    if 'pac' in r: return 'PAC'
    return 'deterministic-approx'
def _progress(c):
    a = c.get('activation') or {}; parts = []
    if a.get('compile_commits'): parts.append('commits %s' % ','.join(a['compile_commits'][:4]))
    if a.get('bias') and any(str(b) not in ('0', 'None') for b in a['bias']): parts.append('bias %s' % ','.join(str(b)[:9] for b in a['bias'][:2]))
    if a.get('ratio_draws'): parts.append('ratio draws %s' % a['ratio_draws'])
    if a.get('signed_epochs'): parts.append('signed epochs %s' % a['signed_epochs'])
    if a.get('frontier'): parts.append('frontier open %s / resolved %s' % (a['frontier'].get('open_cells'), a['frontier'].get('resolved_cells')))
    if a.get('structural_attempts'): parts.append('structural %s' % ';'.join('%s:%s%s' % (x[0], x[1], ('/' + x[2]) if x[2] else '') for x in a['structural_attempts'][:3]))
    ref = a.get('reference') or {}
    if ref and ref.get('progress') is not None: parts.append('ref %.0f%%%s' % (100 * float(ref['progress']), ' done' if ref.get('done') else ''))
    sc = a.get('sidecar') or {}; le = sc.get('last_enclosure_DIAGNOSTIC')
    if isinstance(le, dict) and le.get('max_width') is not None: parts.append('compiled width (diag) max %s' % str(le['max_width'])[:8])
    return '; '.join(parts) or '—'
def _diagnosis(cand, comp, row):
    exp = (row.get('expected_mechanism') or '').lower(); a = cand.get('activation') or {}
    act = []
    if 'signed' in exp: act.append(('signed stream', bool(a.get('signed_epochs'))))
    if 'ratio' in exp: act.append(('ratio stream', bool(a.get('ratio_draws'))))
    if 'quotient' in exp or 'bias' in exp: act.append(('approx quotient commit', any('quotient' in str(x) for x in (a.get('compile_commits') or []))))
    if 'structural' in exp: act.append(('structural route', str(cand.get('route') or '').startswith('structural')))
    cov = ', '.join('%s %s' % (n, 'ACTIVE' if ok else 'NOT exercised') for n, ok in act) or 'n/a'
    if cand['status'] == 'NOT_RUN': return 'NOT RUN (%s)' % cand.get('reason', '')
    if cand.get('hard_failure'): return 'HARD FAILURE: ' + cand['hard_failure']
    co = (comp or {}).get('outcome'); cp = cand['outcome']
    if comp is None: verdict = 'control: %s' % cp
    elif cp == 'PUBLISHED' and co != 'PUBLISHED': verdict = 'candidate publishes where the comparator does not'
    elif cp != 'PUBLISHED' and co == 'PUBLISHED': verdict = 'REGRESSION / LOSS vs comparator (comparator published)'
    elif cp == co == 'PUBLISHED':
        wc, wo = cand.get('wall_s') or 0, comp.get('wall_s') or 0; ratio = (wc / wo) if wo else None
        verdict = 'both publish; wall ratio cand/comp %.2f' % ratio if ratio else 'both publish'
        if ratio and ratio > 1.5: verdict += ' (slower: bounded follow-up, not a gate)'
    else: verdict = 'both %s / %s: ' % (cp, co) + _bottleneck(cand)
    return verdict + '; coverage: ' + cov
def _bottleneck(c):
    a = c.get('activation') or {}; sc = a.get('sidecar') or {}; pt = sc.get('phase_times_s') or {}
    if not a.get('structural_attempts') and not a.get('compile_commits') and not pt: return 'UNKNOWN (no activation telemetry retained; missing observation: certificate / sidecar)'
    big = max(pt.items(), key=lambda kv: kv[1])[0] if pt else None
    if a.get('structural_attempts') and all(x[1] in ('not_admitted', 'declined', 'inapplicable', 'discovery_failed') for x in a['structural_attempts']): head = 'structural not admitted / inapplicable'
    elif a.get('compile_commits') == [] and (a.get('compile_declines') or []): head = 'compiler committed nothing (declines: %s)' % ','.join(d[0] for d in a['compile_declines'][:3])
    elif a.get('ratio_draws') or a.get('signed_epochs'): head = 'streams active but bound not closed within budget'
    elif a.get('frontier') and (a['frontier'].get('open_cells') or 0) > 0: head = 'frontier open (%s cells) at the stop' % a['frontier'].get('open_cells')
    else: head = 'no decisive activation'
    return head + (' ; dominant phase %s (%.2fs)' % (big, pt[big]) if big else '')
def write_md(rec, rows, path):
    h = rec['hypothesis']; L = ['# CQR fast-loop iteration report %s' % (('— ' + rec['label']) if rec.get('label') else ''), '', '**Status: %s** (elapsed %.1f s of the %.0f s cap%s). %s' % (rec['status'], rec['elapsed_s'], rec['cap_s'], '' if rec['within_cap'] else '; CAP EXCEEDED', ('STOP reason: ' + rec['stop_reason']) if rec.get('stop_reason') else ''), '',
         '## Hypothesis (preregistered)', '', '* **Change:** %s' % h.get('change'), '* **Mathematical premise:** %s' % h.get('premise'), '* **Expected favorable behaviour:** %s' % h.get('expected_favorable'), '* **Expected near-miss behaviour:** %s' % h.get('expected_near_miss'), '* **Preserved capabilities:** %s' % '; '.join(h.get('preserved') or []), '',
         '## Identities', '', '| build | git head | cqr scope | full inventory | clean |', '|---|---|---|---|---|']
    for k in ('candidate', 'baseline'):
        i = rec['identities'][k]; L.append('| %s (`%s`) | %s | %s | %s (%s) | %s |' % (k, i.get('build'), str(i.get('git_head'))[:12], str(i.get('cqr_scope_sha256'))[:12], str(i.get('full_inventory_sha256'))[:12], i.get('artifacts'), i.get('tracked_clean')))
    L += ['', 'Manifest %s; harness %s; mode %s; worker nominal %.0f s (cap %.0f s).' % (rec['identities']['manifest_sha256'][:12], rec['harness'], rec['plan']['mode'], rec['plan']['worker_nominal_s'], rec['plan']['allocations']['worker_nominal_s_cap']), '',
          '## Cases', '', '| case / purpose | comparator → candidate | verified route / activation | truth / checker | wall (comp → cand) | approximation progress (candidate) | diagnosis |', '|---|---|---|---|---|---|---|']
    by = {}
    for c in rec['cells']: by.setdefault(c['id'], {})[c['tag']] = c
    for r in rows:
        cs = by.get(r['id'], {}); cand = cs.get('candidate'); comp = cs.get('comparator')
        if cand is None: L.append('| %s | NOT RUN | | | | | |' % r['id']); continue
        ck = cand.get('check') or {}; tr = cand.get('truth') or {}
        L.append('| %s<br>_%s_ | %s → **%s** | %s<br>%s | %s / %s | %s → %s | %s | %s |' % (r['id'], r['block'], ('%s (%s%s)' % (comp['outcome'], comp['arm'], (' ' + comp.get('route')) if comp.get('route') else '')) if comp else ('— (%s)' % (r.get('comparator') or {}).get('kind', 'control')), '%s%s' % (cand['outcome'], (' ' + cand['route']) if cand.get('route') else ''),
                   _route_class(cand), (r.get('expected_mechanism') or '')[:60], '%s%s' % (tr.get('containment', tr.get('status')), (' (%s)' % tr.get('method')) if tr.get('method') else ''), ck.get('status', '—'), ('%.2fs' % comp['wall_s']) if comp else '—', '%.2fs' % (cand.get('wall_s') or 0), _progress(cand), _diagnosis(cand, comp, r)))
    reg = [c for c in rec['cells'] if c['tag'] == 'candidate' and c['outcome'] != 'PUBLISHED' and (by[c['id']].get('comparator') or {}).get('outcome') == 'PUBLISHED' and (by[c['id']].get('comparator') or {}).get('comparator_kind') == 'baseline_N1']
    L += ['', '## Regressions vs the accepted baseline', ''] + (['* **%s**: candidate %s, baseline %s' % (c['id'], c['outcome'], by[c['id']]['comparator']['outcome']) for c in reg] or ['none observed on this panel'])
    L += ['', '## Hard failures, incomplete and skipped', ''] + (['* HARD: %s / %s: %s' % x for x in rec['hard_failures']] or []) + (['* NOT RUN: %s / %s: %s' % x for x in rec['not_run']] or []) + (['* NO OUTPUT: %s / %s' % x for x in rec['no_output']] or []) + (['* UNVERIFIED publication: %s / %s' % x for x in rec['unverified_publications']] or []) + (['none'] if not (rec['hard_failures'] or rec['not_run'] or rec['no_output'] or rec['unverified_publications']) else [])
    L += ['', '## Harness controls (mutations of COPIES; the checker must refuse)', ''] + (['* %s: refused=%s intended_reason=%s — %s' % (m['name'], m['refused'], m['intended_reason'], m['first']) for m in rec['mutation_controls']] or ['not run (no honest smoke publication available or cap exhausted)'])
    L += ['', '## Hard kills / supervisor', ''] + (['* %s / %s: %s survivors=%s' % (c['id'], c['tag'], c['status'], (c.get('supervisor') or {}).get('survivors')) for c in rec['cells'] if c['status'] in ('TIMEOUT_KILL', 'MEMORY_KILL') or (c.get('supervisor') or {}).get('survivors')] or ['none'])
    L += ['', '## Costs', '', '* run elapsed %.1f s; %d supervised cell receipts, %.1f s charged inside them; host %s load %.1f' % (rec['elapsed_s'], rec['charges']['cell_receipts'], rec['charges']['cell_wall_s'], rec['host']['node'], rec['host']['load_avg_1m']), '* every cell: `cells/<n>_<id>__<tag>__<arm>/` (worker.json, worker.diag.json, check.json, stdout/stderr, supervisor receipt in CQR_LEDGER.jsonl)']
    L += ['', '## Limitations', ''] + ['* ' + x for x in rec['limitations']]
    L += ['', '## Next question', '', h.get('question') or ('(regression / calibration run: no change hypothesis declared) — the next implementation must arrive with its own hypothesis file' if not h.get('change') or 'none declared' in str(h.get('change')) else 'Which step of the hypothesis failed? See the diagnosis column: activation (did the mechanism run), benefit (did the original-task uncertainty or end-to-end cost fall), bottleneck (which phase consumed the budget), regression (which preserved capability changed).')]
    open(path, 'w').write('\n'.join(L) + '\n')
