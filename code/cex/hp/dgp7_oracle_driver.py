"""DGP7 oracle phase driver (brief section 9 'Run the oracle mechanism first'; PROTOCOL.md section 3): runs dgp7_oracle.py on every ORACLE_MANIFEST model (12: the eight exposed strong n8 card-4 coupling-2 models + the four fresh
ORACLE7 models) under supervision (scope dgp7_oracle) in the FROZEN priority order: (construct) the production trajectories (RJ / RO), the teacher and the offline injected / uniform laws on all 12 models (cap per model); (anchors1)
replays of seed / RJ_final / RO_final / ideal_q_eq_p on the three exposed n8 reference cliques (original, __oracle4, __oracle5); (anchors2) the same laws on the two fresh ORACLE7 cliques, then the two fresh ORACLE7 ER50 models;
(anchors3) the same laws on the remaining five models in stable model-hash order; (extras) the oracle-injected / uniform-diagnostic / intermediate-epoch replays on the five cliques. The oracle phase stops at its 1,200 s allocation:
remaining planned entries stay explicitly censored (recorded by the analyzer; never claimed). --continue reuses completed replays. Anchor lists come from MODEL_MANIFEST.json panels.replay_anchors (keys exposed_reference_cliques |
exposed_hard_n8_cliques, fresh_cliques, fresh_er, remaining_hash_order); when a key is absent the list is DERIVED from the oracle manifest names (the three reference cliques by name; '__oracle7' names by family; the rest in
model-hash order) and the derivation is printed. usage: dgp7_oracle_driver.py --code-root ROOT [--records RD] [--phase construct|anchors1|anchors2|anchors3|extras|all] [--cap-s 100] [--alloc 1200] [--only NAME[,NAME]] [--allowance-s 3.8]"""
import sys, os, json, time, subprocess, argparse, hashlib
RD = '/Users/adis/Workspace/pgm-records/code/runs/mdi_2026-10-28/DGP7_RESIDUAL_JOINT'; SUP_CODE = os.environ.get('PGM_CODE', '/Users/adis/Workspace/pgm/code'); PY = os.environ.get('PY', os.path.join(SUP_CODE, '.venv/bin/python')); CAFF = os.environ.get('CAFF', '/usr/bin/caffeinate')
PRIORITY_LAWS = 'seed,RJ_final,RO_final,ideal_q_eq_p'; EXTRA_LAWS = 'oracle_injected_true_context,uniform_context_DIAGNOSTIC,offline_proposal_context'
REFERENCE_CLIQUES = ['dg_n8_c4_clique_two', 'dg_n8_c4_clique_two__oracle4', 'dg_n8_c4_clique_two__oracle5']
def charged(ledger, scope): return sum(json.loads(l)['wall_s'] for l in open(ledger) if json.loads(l).get('kind') == 'RECEIPT' and json.loads(l).get('scope') == scope) if os.path.exists(ledger) else 0.0


def run_one(rd, root, t, out_dir, ledger, cap, laws, phase, env, cont, allowance):
    out = os.path.join(out_dir, t['name'] + '.json'); job = 'dgp7:oracle:%s:%s' % (t['name'], phase)
    cmd = [PY, os.path.join(root, 'code/cex/hp/dgp7_oracle.py'), t['model'], out, '--cap-s', str(cap), '--allowance-s', str(allowance)] + (['--replay', '--replay-laws', laws] if laws else []) + (['--continue'] if cont else [])
    sup = [PY, '-m', 'gbidi.supervise', '--ledger', ledger, '--scope', 'dgp7_oracle', '--job', job, '--timeout', str(cap + 15), '--mem-gib', '3', '--interval', '0.05', '--cwd', os.path.join(root, 'code'), '--stdout', os.path.join(out_dir, '%s.%s.stdout.txt' % (t['name'], phase)), '--stderr', os.path.join(out_dir, '%s.%s.stderr.txt' % (t['name'], phase)), '--', CAFF, '-s'] + cmd
    subprocess.run(sup, cwd=SUP_CODE, env=env); r = json.load(open(out)) if os.path.exists(out) else {}
    g = r.get('mechanism_gate') or {}
    print(json.dumps(dict(model=t['name'], phase=phase, cap=cap, wall=r.get('wall_s'), censored=r.get('censored'), gate={k: g.get(k) for k in ('passed', 'M2_gain_bits', 'cap_ratio_vs_best_same_law', 'inside_allowance', 'changed_law_transactions')}, rj=((r.get('stream_rj') or {}).get('transactions_done')), ro=((r.get('stream_ro') or {}).get('transactions_done')), replays={k: ('ok' if isinstance(v, dict) and v.get('caps') else (v.get('censored') or v.get('reason') or 'n/a')) for k, v in (r.get('replays') or {}).items()}), default=str), flush=True)


def derive_anchors(man, anchors):
    """fill the missing anchor lists from the oracle manifest names (printed when used)"""
    names = [t['name'] for t in man]; by = {t['name']: t for t in man}; out = dict(anchors or {}); derived = []
    if not (out.get('exposed_reference_cliques') or out.get('exposed_hard_n8_cliques')): out['exposed_reference_cliques'] = [x for x in REFERENCE_CLIQUES if x in names]; derived.append('exposed_reference_cliques')
    if not out.get('fresh_cliques'): out['fresh_cliques'] = sorted(x for x in names if x.endswith('__oracle7') and 'clique' in x); derived.append('fresh_cliques')
    if not out.get('fresh_er'): out['fresh_er'] = sorted(x for x in names if x.endswith('__oracle7') and 'er50' in x); derived.append('fresh_er')
    if not out.get('remaining_hash_order'):
        used = set((out.get('exposed_reference_cliques') or out.get('exposed_hard_n8_cliques') or []) + out['fresh_cliques'] + out['fresh_er']); out['remaining_hash_order'] = sorted([x for x in names if x not in used], key=lambda x: by[x].get('model_sha256') or x); derived.append('remaining_hash_order')
    if derived: print('anchor lists DERIVED from the oracle manifest (keys absent in MODEL_MANIFEST.panels.replay_anchors):', derived, json.dumps({k: out[k] for k in derived}))
    return out


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--code-root', required=True); ap.add_argument('--records', default=RD); ap.add_argument('--phase', default='all', choices=['construct', 'anchors1', 'anchors2', 'anchors3', 'extras', 'all']); ap.add_argument('--cap-s', type=float, default=100.0); ap.add_argument('--alloc', type=float, default=1200.0); ap.add_argument('--only', default=None); ap.add_argument('--allowance-s', type=float, default=3.8); a = ap.parse_args()
    rd = a.records; root = os.path.abspath(a.code_root); mm = json.load(open(os.path.join(rd, 'MODEL_MANIFEST.json'))); man = json.load(open(os.path.join(rd, 'ORACLE_MANIFEST.json')))['tasks']; by = {t['name']: t for t in man}; anchors = derive_anchors(man, (mm.get('panels') or {}).get('replay_anchors'))
    ref = anchors.get('exposed_reference_cliques') or anchors.get('exposed_hard_n8_cliques')
    ledger = os.path.join(rd, 'DGP7_LEDGER.jsonl'); out_dir = os.path.join(rd, 'oracle', 'results'); os.makedirs(out_dir, exist_ok=True); env = dict(os.environ, OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1', VECLIB_MAXIMUM_THREADS='1'); env.pop('PYTHONPATH', None)
    import dgp_paths
    for t in man: t['model'] = dgp_paths.resolve_input(t['model'], rd, t.get('model_sha256'))
    def left(): return a.alloc - charged(ledger, 'dgp7_oracle')
    def done(name, laws):
        p = os.path.join(out_dir, name + '.json')
        if not os.path.exists(p): return False
        d = json.load(open(p))
        if d.get('censored') or not d.get('mechanism_gate'): return False
        return all((k in (d.get('replays') or {}) and (d['replays'][k].get('caps') or d['replays'][k].get('not_available'))) for k in (laws.split(',') if laws else []))
    only = set(a.only.split(',')) if a.only else None
    phases = []
    if a.phase in ('construct', 'all'): phases.append(('construct', [t['name'] for t in man], None))
    if a.phase in ('anchors1', 'all'): phases.append(('anchors1', list(ref), PRIORITY_LAWS))
    if a.phase in ('anchors2', 'all'): phases.append(('anchors2', list(anchors['fresh_cliques']) + list(anchors['fresh_er']), PRIORITY_LAWS))
    if a.phase in ('anchors3', 'all'): phases.append(('anchors3', list(anchors['remaining_hash_order']), PRIORITY_LAWS))
    if a.phase in ('extras', 'all'): phases.append(('extras', list(ref) + list(anchors['fresh_cliques']), PRIORITY_LAWS + ',' + EXTRA_LAWS))
    for phase, names, laws in phases:
        for name in names:
            if only and name not in only: continue
            if name not in by: print('skip (not in the oracle manifest):', name); continue
            p = os.path.join(out_dir, name + '.json')
            if phase == 'construct' and os.path.exists(p) and not json.load(open(p)).get('censored') and json.load(open(p)).get('mechanism_gate'): print('construct: complete output exists for', name); continue
            if phase != 'construct' and done(name, laws): print(phase, 'complete for', name); continue
            rem = left()
            if rem < 20: print('ORACLE ALLOWANCE EXHAUSTED (%.1f s left) before %s %s: the remaining planned entries stay censored' % (rem, phase, name)); return
            run_one(rd, root, by[name], out_dir, ledger, min(a.cap_s, rem), laws, phase, env, cont=(phase != 'construct'), allowance=a.allowance_s)
    print('oracle phase done; charged %.1f s of %.0f' % (charged(ledger, 'dgp7_oracle'), a.alloc))


if __name__ == '__main__': main()
