"""DGP9 freeze + manifests (derived from dgp8_manifests.py; PROTOCOL.md sections 2-6). `freeze` writes FREEZE.json (implementation, configuration, runner / analyzer / probe / validator identities, the native build identities, dependency
identities, the spectral-witness / certificate / transition-policy constants incl. the FROZEN mechanism-change constants (proposal margins E0 / R / K; plan N_1 rule, rho_N, J_max; summable risks), the panels, the gates, the budget incl.
recorded reassignments, the frozen rate-model file hash when present). `holdout` (run at the frozen commit from the clean detached checkout) VERIFIES byte-identical the 7 exposed primary / control inputs and the 24 / 18 / 13
preservation inputs, GENERATES the 5 fresh matched inputs (dense_gen eval9; tag DGP9/EVAL9/) into <RD>/inputs/fresh, copies EVERY manifest input's bytes into <RD>/inputs/<panel>/ (packet-relative replay; review RV7), reads the
archived incumbents (DGP8 SPECTRAL_HEATBATH certified radii and the DGP6 / DGP7 REPAIRED best worst radii by task name), and writes MODEL_MANIFEST.json + the per-panel manifests consumed by run_dgp9.py: MAIN_EXPOSED (7: 5 primary +
2 strong controls), FRESH (5), PRESERVATION_24 / _18 / _13. usage: dgp9_manifests.py freeze|holdout [--code-root ROOT]"""
import sys, os, json, hashlib, time, subprocess, platform, glob, shutil
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
RD = os.environ.get('DGP9_RD', '/Users/adis/Workspace/pgm-records/code/runs/mdi_2026-10-28/DGP9_SPECTRAL_HEATBATH_CONTINUATION'); ROOT_RUNS = os.path.dirname(RD); DGP8 = os.path.join(ROOT_RUNS, 'DGP8_SPECTRAL_HEATBATH'); DGP7 = os.path.join(ROOT_RUNS, 'DGP7_RESIDUAL_JOINT'); DGP6 = os.path.join(ROOT_RUNS, 'DGP6_GLOBAL_CONSTRUCTION')
PRIMARY = ['dg_n64_c2_er50_half', 'dg_n64_c2_clique_half', 'dg_n64_c4_er50_half', 'dg_n64_c4_clique_half', 'dg_n32_c4_er50_half']; STRONG_CONTROLS = ['dg_n64_c4_er50_two', 'dg_n64_c4_clique_two']
def sha(p): return hashlib.sha256(open(p, 'rb').read()).hexdigest()
def git(root, *a): return subprocess.check_output(['git', '-C', root] + list(a)).decode().strip()


def verify(tasks, rd=None):
    import dgp_paths
    out = []
    for t in tasks:
        p = dgp_paths.resolve_input(t['model'], rd or RD, t.get('model_sha256')); h = sha(p)
        if t.get('model_sha256') and h != t['model_sha256']: raise SystemExit('input hash mismatch: %s' % t['name'])
        out.append(dict(t, model=p, model_sha256=h, verified=True))
    return out


def archived_incumbents():
    """per task name: the DGP8 heat-bath certified worst radius per seed (SPECTRAL_HEATBATH guard cells) and the repaired-engine best worst radius (DGP7 / DGP6 REPAIRED tables; the DGP8 REPAIRED guard cells); current_failure = no
    REPAIRED / BASE completion in DGP6 / DGP7 / DGP8"""
    inc = {}
    def add(name, arm, cell, src):
        if not isinstance(cell, dict): return
        r = cell.get('worst_radius'); r = cell.get('max_published_radius') if r is None else r; comp = bool(cell.get('complete')); e = inc.setdefault(name, dict(cells=[], any_complete=False, best_worst_radius=None, best_cell=None, dgp8_heatbath_radii={}))
        e['cells'].append(dict(arm=arm, src=src, radius=r, complete=comp)); e['any_complete'] = e['any_complete'] or comp
        if arm in ('REPAIRED', 'BASE') and isinstance(r, (int, float)) and (e['best_worst_radius'] is None or r < e['best_worst_radius']): e['best_worst_radius'] = r; e['best_cell'] = '%s/%s' % (src, arm)
    for src, rd_ in (('dgp6', DGP6), ('dgp7', DGP7), ('dgp8', DGP8)):
        R_ = json.load(open(os.path.join(rd_, 'RESULTS.json'))) if os.path.exists(os.path.join(rd_, 'RESULTS.json')) else {}
        for sub, rows in (R_.get('tables') or {}).items():
            for row in rows:
                for arm, cell in (row.get('arms') or {}).items():
                    if arm in ('REPAIRED', 'BASE'): add(row['task'], arm, cell, '%s/%s' % (src, sub))
                    if src == 'dgp8' and arm == 'SPECTRAL_HEATBATH' and sub == 'guard': inc.setdefault(row['task'], dict(cells=[], any_complete=False, best_worst_radius=None, best_cell=None, dgp8_heatbath_radii={}))['dgp8_heatbath_radii'][str(row.get('seed_index'))] = (cell or {}).get('worst_radius')
    for e in inc.values():
        if e['best_worst_radius'] is None and e['cells']: e['best_worst_radius'] = 0.5
        e['current_failure'] = (not e['any_complete']) and (e['best_worst_radius'] is None or e['best_worst_radius'] > 0.005)
    return inc


def freeze(root):
    import run_dgp9 as R9, spectral_witness as SW, markov_certificate as MC, heatbath_native as HN, spectral_heatbath_run as SHR
    import dgp_paths, numpy, scipy
    commit = git(root, 'rev-parse', 'HEAD'); tree = git(root, 'rev-parse', 'HEAD^{tree}'); dirty = git(root, 'status', '--porcelain', '--untracked-files=no', '--', 'code/cex', 'code/gbidi')
    if dirty: raise SystemExit('dirty checkout: %s' % dirty[:200])
    files = R9.identity(root); harness = ['cex/hp/run_dgp9.py', 'cex/hp/run_dgp8.py', 'cex/hp/run_dgp7.py', 'cex/hp/dgp9_manifests.py', 'cex/hp/dgp9_analyze.py', 'cex/hp/dgp9_theory_return.py', 'cex/hp/dgp9_start_here.py', 'cex/hp/dgp9_package.py', 'cex/hp/dgp9_sidecar.py', 'cex/hp/dgp9_probes.py', 'cex/hp/dgp9_rates.py', 'cex/hp/dgp_paths.py', 'cex/hp/validate_round.py', 'cex/hp/check_dgp.py', 'cex/hp/dense_gen.py', 'cex/hp/hp_gen.py']
    hf = {f: (sha(os.path.join(root, 'code', f)) if os.path.exists(os.path.join(root, 'code', f)) else None) for f in harness}
    bud = json.load(open(os.path.join(RD, 'BUDGET_DECLARATION.json'))); prot = sha(os.path.join(RD, 'PROTOCOL.md')); hb_build = os.path.join(root, 'code', 'cex', 'hp', 'heatbath_build.json'); rates = os.path.join(RD, 'HEATBATH_RATES.json')
    fr = dict(experiment='DGP9_SPECTRAL_HEATBATH_CONTINUATION', step='freeze (protocol + code before any scored outcome)', frozen_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), protocol_sha256=prot, brief_sha256=sha(os.path.join(RD, 'PACKET', 'CLAUDE_DGP8_REPAIR_AND_CONTINUATION.md')), review_sha256=sha(os.path.join(RD, 'PACKET', 'DGP8_INDEPENDENT_REVIEW_2026-11-26.md')), evidence_zip_sha256=sha(os.path.join(RD, 'PACKET', 'DGP8_INDEPENDENT_REVIEW_EVIDENCE_2026-11-26.zip')),
              harness_files=hf, harness_files_absent_at_freeze=[f for f, h in hf.items() if h is None], arm_identity_files=list(files),
              code=dict(commit=commit, tree=tree, branch='dgp9-heatbath-continuation', parent='ebf994c (the dgp8-spectral-heatbath tip: frozen DGP8 engine ad20e73 + two harness amendments 4f00754 / ebf994c)', pinned_parent_for_before_probes='ad20e73 (restored by the review packet)', files=files, runner_version=SHR.VERSION, heatbath_kernel=(json.load(open(hb_build)) if os.path.exists(hb_build) else None), dependencies=dict(python=sys.version.split()[0], numpy=numpy.__version__, scipy=scipy.__version__, platform=platform.platform(), compiler=subprocess.check_output(['clang', '--version']).decode().split('\n')[0])),
              arms=dict(R9.ARM_ARGS, production=list(R9.PRODUCTION_ARMS), diagnostic=list(R9.DIAGNOSTIC_ARMS), rotation=R9.FROZEN['arm_rotation'], seed_rule=R9.FROZEN['seed_rule'], select='NOT IMPLEMENTED this round (no frozen request-level risk allocation; deployability reported as standalone-only)'),
              heatbath=dict(witness=SW.PROFILE, native=HN.PROFILE, certificate=MC.PROFILE, runner=dict(reserve_s=SHR.PROFILE['reserve_s'], default_rate_steps_per_s=SHR.PROFILE['default_rate_steps_per_s'], exact_chain_rate_steps_per_s=SHR.PROFILE['exact_chain_rate_steps_per_s'], batch_steps=SHR.PROFILE['batch_steps'], fixed=SHR.PROFILE['fixed'], revised=SHR.PROFILE['revised'], publication=SHR.PROFILE['publication']),
                            mechanism_change_A=dict(policy='revised', extra_margins=SW.POLICY_REVISED['extra_margins'], E0=1e-8, R=4, K=4, stop='first success | u - l + 2 e_k >= 2 | sequence exhausted | work clock', development_evidence='DGP8 review probe_clique_margin_and_memory: the weak n64 card-4 clique proves at +1e-8 per side (0.07 s); the DGP9 smoke / D83 boundary cases'),
                            mechanism_change_B=dict(policy='revised', N1_rule=SHR.PROFILE['revised']['N1_rule'], rho_N=SHR.PROFILE['revised']['rho_N'], J_max=SHR.PROFILE['revised']['J_max'], risks='delta_sample / (j (j + 1))', development_evidence='checkpoint overhead 0.7-0.8 ms per checkpoint at K = 128 (smoke2 / D87): 64 checkpoints cost < 60 ms of a 19 s allowance; rho_N = 1.25 bounds the unused tail of the last interval to 20 % of its length'),
                            rate_model=(dict(path='HEATBATH_RATES.json', sha256=sha(rates)) if os.path.exists(rates) else 'NOT YET (written by dgp9_rates.py after the screen; the heat-bath arms REQUIRE it)')),
              panels=dict(primary=PRIMARY, strong_controls=STRONG_CONTROLS, fresh='dense_gen eval9 (DGP9/EVAL9/): 5 matched weak inputs generated at holdout', preservation=['PRESERVATION_24 (DGP8 HISTORICAL_24_MANIFEST)', 'PRESERVATION_18', 'PRESERVATION_13'], seeds=[0, 1], seed_1_reversed=True),
              gates=dict(validity='D1-D90 all pass from the clean checkout; dgp9_probes RV1-RV7 ABSENT at the frozen commit (PRESENT on the pinned parent); the recovered references pass; no late row; ledger identity on every heat-bath cell', mechanism='weak-clique admission with a checked source / gap (HB_REVISED both seeds); HB_REVISED last completed N > HB_FIXED N_max on the near-misses', inference='observed epsilon completion on a current failure in BOTH seeds = NEW COMPLETION; equal-cost worst-radius ratios HB_REVISED / HB_FIXED and HB / INCUMBENT; ER gain RETAINED iff HB_REVISED worst radius <= 1.1 x the DGP8 certified radius in both seeds', preservation_cost='INCUMBENT loses no completion on 24 / 18 / 13; overhead where both complete (1.25x and +0.1 s)', generalization='fresh separately; no strong-frustration conclusion'),
              contracts=R9.CONTRACTS, memory=dict(supervisor_gib=R9.FROZEN['mem_gib'], constructor_bytes=128 << 20), budget=bud)
    json.dump(fr, open(os.path.join(RD, 'FREEZE.json'), 'w'), indent=1, default=str); print(json.dumps(dict(commit=commit[:12], identity_files=len(files), harness_absent=fr['harness_files_absent_at_freeze'], rate_model=('present' if os.path.exists(rates) else 'absent')))); return fr


def holdout(root):
    import dgp_paths
    fr = json.load(open(os.path.join(RD, 'FREEZE.json'))); head = git(root, 'rev-parse', 'HEAD')
    if head != fr['code']['commit']: raise SystemExit('holdout must run at the frozen commit %s (checkout %s)' % (fr['code']['commit'][:12], head[:12]))
    m8 = json.load(open(os.path.join(DGP8, 'MODEL_MANIFEST.json'))); P8 = m8['panels']; by_name = {t['name']: t for t in P8['stage_a_16']}; inc = archived_incumbents()
    def task(name, role):
        t = dict(by_name[name]); t['role'] = role; t['archived_incumbent'] = inc.get(name); return t
    exposed = [task(n, 'primary_weak' if n != 'dg_n32_c4_er50_half' else 'matched_passing') for n in PRIMARY] + [task(n, 'strong_refusal_control') for n in STRONG_CONTROLS]; exposed = verify(exposed)
    fresh_dir = os.path.join(RD, 'inputs', 'fresh'); os.makedirs(fresh_dir, exist_ok=True)
    gen = subprocess.run([sys.executable, os.path.join(root, 'code', 'cex', 'hp', 'dense_gen.py'), 'eval9', fresh_dir], capture_output=True, text=True, timeout=600)
    if gen.returncode != 0: raise SystemExit('fresh generation failed: %s' % gen.stderr[-400:])
    gman = json.load(open(os.path.join(fresh_dir, 'MANIFEST.json'))) if os.path.exists(os.path.join(fresh_dir, 'MANIFEST.json')) else None
    fresh = []
    for p in sorted(glob.glob(os.path.join(fresh_dir, '*.uai'))):
        name = os.path.basename(p)[:-4]; parts = name.split('_'); n = int(parts[1][1:]); card = int(parts[2][1:]); topo = parts[3]; coup = parts[4]
        fresh.append(dict(name=name + '__eval9', model=p, model_sha256=sha(p), n=n, card=card, topology=topo, family=topo, coupling=coup, role='fresh_matched_weak', generator='dense_gen eval9 (DGP9/EVAL9/)', archived_incumbent=None))
    def pres(name_json, panel):
        t_ = json.load(open(os.path.join(DGP8, name_json)))['tasks']
        for t in t_: t['role'] = 'preservation'; t['archived_incumbent'] = inc.get(t['name'])
        return verify(t_)
    p24 = pres('HISTORICAL_24_MANIFEST.json', 'preservation_24'); p18 = pres('PRESERVATION_18_MANIFEST.json', 'preservation_18'); p13 = pres('PRESERVATION_13_MANIFEST.json', 'preservation_13')
    # packet-relative copies of EVERY manifest input (bytes shipped; review RV7)
    copied = {}
    for panel, tasks in (('exposed', exposed), ('preservation_24', p24), ('preservation_18', p18), ('preservation_13', p13)):
        d = os.path.join(RD, 'inputs', panel); os.makedirs(d, exist_ok=True)
        for t in tasks:
            dst = os.path.join(d, os.path.basename(t['model'])); shutil.copyfile(t['model'], dst)
            if os.path.exists(t['model'] + '.evid'): shutil.copyfile(t['model'] + '.evid', dst + '.evid')
            t['packet_copy'] = os.path.relpath(dst, RD); copied[t['name']] = t['packet_copy']
    for t in fresh: t['packet_copy'] = os.path.relpath(t['model'], RD)
    man = dict(utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), code_commit=head, inputs_shipped_in_packet=True, panels=dict(main_exposed=exposed, fresh=fresh, preservation_24=p24, preservation_18=p18, preservation_13=p13), fresh_generation=dict(kind='eval9', tag='DGP9/EVAL9/', manifest=gman, generator_sha256=sha(os.path.join(root, 'code', 'cex', 'hp', 'dense_gen.py'))), archived_incumbents_source='DGP6 / DGP7 / DGP8 RESULTS.json tables by task name (REPAIRED / BASE best worst radius; DGP8 SPECTRAL_HEATBATH guard radii per seed)',
               note='exposed = 5 primary (4 weak current failures + the matched passing n32 card-4 ER) + 2 strong twins (negative admission controls); fresh = 5 matched weak inputs generated AFTER the freeze; preservation = the 24 historical DGP6 completions, the 18 (4 s) and 13 (20 s) accepted panels (INCUMBENT only)')
    json.dump(man, open(os.path.join(RD, 'MODEL_MANIFEST.json'), 'w'), indent=1, default=str)
    for fn, tasks, panel in (('MAIN_EXPOSED_MANIFEST.json', exposed, 'main_exposed'), ('FRESH_MANIFEST.json', fresh, 'fresh'), ('PRESERVATION_24_MANIFEST.json', p24, 'preservation_24'), ('PRESERVATION_18_MANIFEST.json', p18, 'preservation_18'), ('PRESERVATION_13_MANIFEST.json', p13, 'preservation_13')):
        json.dump(dict(panel=panel, code_commit=head, tasks=tasks), open(os.path.join(RD, fn), 'w'), indent=1, default=str)
    print(json.dumps(dict(exposed=len(exposed), fresh=[t['name'] for t in fresh], p24=len(p24), p18=len(p18), p13=len(p13), copied=len(copied), incumbents={n: (inc.get(n) or {}).get('best_worst_radius') for n in PRIMARY + STRONG_CONTROLS})))


if __name__ == '__main__':
    import argparse; ap = argparse.ArgumentParser(); ap.add_argument('step', choices=['freeze', 'holdout']); ap.add_argument('--code-root', default='/Users/adis/Workspace/pgm-dgp9'); a = ap.parse_args()
    (freeze if a.step == 'freeze' else holdout)(os.path.abspath(a.code_root))
