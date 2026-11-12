"""LOCKED-PLAN comparison (prompt section 8 step 3) -- v3 (follow-up review §5: a FRESH ATTEMPT DIRECTORY is required (an existing one is refused); an arm is accepted
only if ITS child exited 0 within the delivery budget AND wrote an output carrying this invocation's nonce and the plan / arm binding; coordinate shapes are checked
against the serialized plan before any containment loop; v2: FRESH PROCESS PER ARM with its own peak RSS and a sampled-RSS watchdog per arm; exact coordinates RETAINED). The UNCHANGED baseline planner (cex/baseline core._discover_component, charged) produces
the component plan in the parent; the plan (component models with exact rational values + selected orders) is serialized once; EACH executor then runs in its
own fresh subprocess from the SAME serialized validated plan: baseline = support.solve (exact Fraction); new = cex_executor.execute (compiled, certified binary64 +
labels). The parent records per arm: status / wall / the child's own ru_maxrss / sampled tree RSS peak / counters, and cross-checks that every compiled enclosure
contains the exact reference point; both arms' intervals and points are retained as exact strings so the containment can be recomputed from this file alone.
    python cex/locked_plan.py <case> <outdir> <budget_s> [cap_bytes] [arms]"""
import sys, os, json, time, subprocess, hashlib, signal, threading
sys.set_int_max_str_digits(0); HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, 'baseline'))
from fractions import Fraction as F
P = '/Users/adis/Workspace/pgm/docs/handoff-received-2026-11-11-certified-executor/packet/inputs'
CHILD = r'''
import sys, os, json, time, resource; sys.set_int_max_str_digits(0)
from fractions import Fraction as F
arm, planp, outp, budget, cap, here, nonce = sys.argv[1], sys.argv[2], sys.argv[3], float(sys.argv[4]), int(sys.argv[5]), sys.argv[6], sys.argv[7]   # here = the cex/ code directory; nonce = this invocation's identity (the parent accepts only an output carrying it)
import hashlib; plan_sha = hashlib.sha256(open(planp, 'rb').read()).hexdigest(); plan = json.load(open(planp)); comps = [(c['old'], dict(cards=c['cards'], factors=[dict(scope=tuple(f['scope']), values=[F(x) for x in f['values']]) for f in c['factors']], evidence={}), c['order']) for c in plan['support_components']]
def rss(): r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss; return r if sys.platform == 'darwin' else r * 1024
rss_entry = rss(); t_arm = time.monotonic(); rows = []; status = 'COMPLETED'; stop = None
if arm == 'baseline': sys.path.insert(0, os.path.join(here, 'baseline')); import support
else: sys.path.insert(0, os.path.join(here, 'newarm')); import cex_executor as X
for ci, (old, cm, order) in enumerate(comps):
    tc = time.monotonic(); dl = t_arm + budget
    try:
        if arm == 'baseline':
            r = support.solve(cm, deadline=dl, order=order); st = r['stats']
            rows.append(dict(component=ci, variables=len(old), status=r['status'], wall_s=time.monotonic() - tc, forward_s=st.get('forward_s'), reverse_s=st.get('reverse_s'), forward_support_rows=st.get('forward_support_rows'), messages_entries=st.get('messages_entries'), max_numerator_bits=st.get('max_numerator_bits'), mults=st.get('multiplications'), adds=st.get('additions'), divisions=st.get('divisions'), intervals=[[[str(a), str(b)] for a, b in row] for row in r['intervals']], points=[[str(x) for x in row] for row in r['points']]))
        else:
            r = X.execute(cm, order, deadline=dl, cap_bytes=cap, host_reserved_bytes=rss()); st = r['stats']
            rows.append(dict(component=ci, variables=len(old), status=r['status'], wall_s=time.monotonic() - tc, build_s=st.get('build_s'), lowering_s=st.get('lowering_s'), kernel_s=st.get('kernel_s'), enclosure_s=st.get('enclosure_s'), counters=st.get('counters'), max_label_K=st.get('max_label_K'), max_width=st.get('max_width_float'), semantic_plan_sha256=r['certificate']['semantic_plan_sha256'], physical_schedule_sha256=r['certificate']['physical_schedule_sha256'], kernel=r['certificate']['kernel'], kernel_cap_bytes=st.get('kernel_cap_bytes'), host_measured={k: st.get(k) for k in ('host_lowering_rss_growth_bytes_measured', 'host_lowering_retained_bytes_counted', 'host_plan_output_arrays_bytes', 'host_enclosure_rss_growth_bytes_measured')}, intervals=[[[str(a), str(b)] for a, b in row] for row in r['intervals']], points=[[str(x) for x in row] for row in r['points']]))
    except Exception as e:
        status = 'STOPPED'; stop = dict(type=type(e).__name__, kind=getattr(e, 'kind', None), reason=str(e)[:300], stats={k: v for k, v in (getattr(e, 'stats', {}) or {}).items() if k != 'core_trace'}); rows.append(dict(component=ci, variables=len(old), status='STOPPED', wall_s=time.monotonic() - tc)); break
json.dump(dict(arm=arm, nonce=nonce, plan_sha256=plan_sha, status=status, wall_s=time.monotonic() - t_arm, peak_rss_bytes_this_process=rss(), rss_at_entry_bytes=rss_entry, stop=stop, components=rows), open(outp, 'w'), default=str)
sys.exit(0 if status == 'COMPLETED' else 3)
'''
def main():
    case, outdir, budget = sys.argv[1], sys.argv[2], float(sys.argv[3]); cap = int(sys.argv[4]) if len(sys.argv) > 4 else 3 * 1024 ** 3; arms = sys.argv[5].split(',') if len(sys.argv) > 5 else ['new', 'baseline']
    if os.path.exists(outdir): raise SystemExit('refuse: attempt directory %s exists (every attempt gets a fresh directory; failed attempts are preserved, never resumed)' % outdir)
    os.makedirs(outdir); import core, reduction
    import secrets; nonce = secrets.token_hex(8)
    out = {'case': case, 'budget_s': budget, 'cap_bytes': cap, 'attempt_nonce': nonce, 'policy': 'fresh attempt directory; fresh process per arm; an arm is COMPLETED only if its child exited 0 within budget + grace and its output carries this attempt nonce + plan hash + arm; shapes checked against the serialized plan; per-arm sampled-RSS watchdog (MEMORY_KILL); exact coordinates retained'}
    t0 = time.monotonic(); m, binding = core.read_uai(os.path.join(P, case + '.uai')); out['binding'] = binding; out['parse_s'] = time.monotonic() - t0
    t = time.monotonic(); red = reduction.reduce(m, deadline=time.monotonic() + budget); rm = red['model']; split = core.components(rm, deadline=time.monotonic() + budget); plans = []
    for old, cm in split:
        p = core._discover_component(cm, time.monotonic() + budget, 'auto'); plans.append((old, cm, p))
    out['plan_construction_s'] = time.monotonic() - t; out['components'] = [dict(variables=len(old), route=p['kind'], forecast=p['forecast'], order_len=len(p['order'])) for old, cm, p in plans]
    out['reduction'] = {k: red['stats'].get(k) for k in ('aliases', 'states_removed', 'scalar_factors_cancelled')}
    support_comps = [(old, cm, p) for old, cm, p in plans if p['kind'] == 'support']
    if not support_comps:
        out['note'] = 'no support-route component: the locked-plan comparison targets the nonnegative contraction executor only'; json.dump(out, open(os.path.join(outdir, case + '.json'), 'w'), indent=1, default=str); print(json.dumps(out, default=str)[:400]); return
    planp = os.path.join(outdir, case + '.plan.json'); plan = dict(case=case, binding=binding, support_components=[dict(old=old, cards=cm['cards'], order=list(p['order']), factors=[dict(scope=list(f['scope']), values=[str(x) for x in f['values']]) for f in cm['factors']]) for old, cm, p in support_comps])
    json.dump(plan, open(planp, 'w')); out['plan_sha256'] = hashlib.sha256(open(planp, 'rb').read()).hexdigest(); childp = os.path.join(outdir, '_locked_plan_child.py'); open(childp, 'w').write(CHILD)
    res = {}
    for arm in arms:
        armout = os.path.join(outdir, '%s.%s.json' % (case, arm)); t_arm = time.monotonic()
        if os.path.exists(armout): raise SystemExit('refuse: %s exists before the child ran' % armout)
        proc = subprocess.Popen([sys.executable, childp, arm, planp, armout, str(budget), str(cap), HERE, nonce], cwd=HERE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
        watch = {'peak': 0, 'killed': False, 'stop': False}
        def watchdog():
            try: import psutil
            except ImportError: return
            while not watch['stop']:
                try: pr = psutil.Process(proc.pid); r_ = pr.memory_info().rss + sum(c.memory_info().rss for c in pr.children(recursive=True))
                except Exception: return
                watch['peak'] = max(watch['peak'], r_)
                if r_ > cap: watch['killed'] = True; os.killpg(proc.pid, signal.SIGKILL); return
                time.sleep(0.05)
        th = threading.Thread(target=watchdog, daemon=True); th.start()
        try: so, se = proc.communicate(timeout=budget + 30); kind = 'EXIT'
        except subprocess.TimeoutExpired: os.killpg(proc.pid, signal.SIGKILL); so, se = proc.communicate(); kind = 'TIMEOUT_KILL'
        watch['stop'] = True; th.join(timeout=1.0)
        if watch['killed']: kind = 'MEMORY_KILL'
        rec = json.load(open(armout)) if os.path.exists(armout) else dict(arm=arm, status='NO_OUTPUT', components=[])
        rec.update(process_outcome=kind, returncode=proc.returncode, parent_measured_wall_s=time.monotonic() - t_arm, peak_tree_rss_bytes_sampled=watch['peak'], stderr_tail=se[-600:])
        # ACCEPTANCE (v3): the arm is COMPLETED only if THIS child exited 0 (EXIT), within budget + grace, and wrote an output bound to this attempt (nonce), this plan and this arm,
        # whose coordinate shapes match the serialized plan (one row per component variable, each of the variable's cardinality); anything else is a typed rejection, the file kept
        reasons = []
        if kind != 'EXIT': reasons.append('process outcome %s' % kind)
        if proc.returncode != 0: reasons.append('child returncode %s' % proc.returncode)
        if rec.get('nonce') != nonce: reasons.append('output nonce does not match this attempt (stale or foreign output)')
        if rec.get('plan_sha256') != out['plan_sha256']: reasons.append('output plan hash does not match the serialized plan')
        if rec.get('arm') != arm: reasons.append('output arm label mismatch')
        if rec.get('parent_measured_wall_s', 0) > budget + 30: reasons.append('delivery after budget + grace')
        if rec.get('status') == 'COMPLETED':
            comps = rec.get('components') or []
            if len(comps) != len(plan['support_components']): reasons.append('component count %d differs from the plan (%d)' % (len(comps), len(plan['support_components'])))
            for c_, pc in zip(comps, plan['support_components']):
                iv = c_.get('intervals') or []; pts = c_.get('points') or []
                if len(iv) != len(pc['cards']) or len(pts) != len(pc['cards']) or any(len(row) != k or len(pr) != k for row, pr, k in zip(iv, pts, pc['cards'])): reasons.append('component %s coordinate shape differs from the plan' % c_.get('component'))
        if reasons and rec.get('status') == 'COMPLETED': rec['status'] = 'REJECTED'
        if reasons: rec['rejection_reasons'] = reasons
        res[arm] = rec
        out['executors'] = {a: {k: v for k, v in r.items() if k != 'components'} | {'components': [{k: v for k, v in c.items() if k not in ('intervals', 'points')} for c in r.get('components', [])]} for a, r in res.items()}
        json.dump(out, open(os.path.join(outdir, case + '.json'), 'w'), indent=1, default=str)      # persist after EVERY arm
    # ---- cross-check: the new arm's enclosures contain the exact reference points where both completed (recomputable from the retained coordinates)
    if res.get('new', {}).get('status') == 'COMPLETED' and res.get('baseline', {}).get('status') == 'COMPLETED':
        allc = True; coords = 0; worst = F(0)
        for rn, rb in zip(res['new']['components'], res['baseline']['components']):
            for row, ps in zip(rn['intervals'], rb['points']):
                for (lo, hi), p in zip(row, ps): coords += 1; lo, hi, p = F(lo), F(hi), F(p); c_ = lo <= p <= hi; allc = allc and c_; worst = max(worst, (lo - p) if p < lo else (p - hi) if p > hi else F(0))
        out['new_encloses_exact_reference'] = allc; out['coordinates_compared'] = coords; out['worst_excursion'] = str(worst)
    out['retained_coordinates'] = {a: [dict(component=c['component'], intervals=c.get('intervals'), points=c.get('points')) for c in r.get('components', [])] for a, r in res.items()}
    out['semantic_plan_identical_across_arms'] = 'by construction: both child processes load the same serialized plan file (plan_sha256); the new arm records the semantic hash'
    json.dump(out, open(os.path.join(outdir, case + '.json'), 'w'), indent=1, default=str)
    print(json.dumps({k: out.get(k) for k in ('case', 'plan_construction_s', 'components', 'new_encloses_exact_reference', 'coordinates_compared', 'worst_excursion')}, default=str))
    print(json.dumps({a: {k: v for k, v in r.items() if k not in ('components', 'stderr_tail')} | {'comp0': {k: v for k, v in (r['components'][0] if r.get('components') else {}).items() if k not in ('counters', 'intervals', 'points')}} for a, r in res.items()}, default=str)[:1800])
if __name__ == '__main__': main()
