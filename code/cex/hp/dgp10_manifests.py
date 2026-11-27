"""DGP10 freeze + manifests (derived from dgp9_manifests.py; FROZEN_EXPERIMENT_SPEC sections 2, 4, 6). `freeze` writes FREEZE.json (implementation, configuration, runner / analyzer / probe / validator identities, the native build identity,
dependency identities, the witness / certificate / transition-policy constants, the DGP10 response constants (local plan, centers, tilts, risks, tail rule, checker identity = the packet reference's sha256), the panels, the gates, the
budget incl. recorded reassignments, BOTH frozen rate files by hash (HEATBATH_RATES.json = the exact DGP9 bytes for HB_R; RESPONSE_RATES.json for RESPONSE), the normative inventory hash). `holdout` (run at the frozen commit from the
clean detached checkout) VERIFIES byte-identical the 12 EXPOSED inputs (DGP9's 7 exposed + its 5 former fresh, now exposed) and the 24 / 18 / 13 preservation inputs against the DGP9 manifests / packet copies, GENERATES the 7 fresh
inputs (dense_gen eval10; tag DGP10/EVAL10/: five matched weak + two strong twins), binds the DGP9-SAMPLE seeds of the exposed inputs (checked against the archived DGP9 cells) and the DGP10-SAMPLE seeds of the fresh inputs, copies EVERY
manifest input's bytes into <RD>/inputs/<panel>/ and writes MODEL_MANIFEST.json + the per-panel manifests consumed by run_dgp10.py. usage: dgp10_manifests.py freeze|holdout [--code-root ROOT]"""
import sys, os, json, hashlib, time, subprocess, platform, glob, shutil
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
RD = os.environ.get('DGP10_RD', '/Users/adis/Workspace/pgm-records/code/runs/mdi_2026-10-28/DGP10_QUERY_RESPONSE'); ROOT_RUNS = os.path.dirname(RD); DGP9 = os.environ.get('DGP10_DGP9_RECORDS', os.path.join(ROOT_RUNS, 'DGP9_SPECTRAL_HEATBATH_CONTINUATION'))
PKT = os.environ.get('DGP10_PACKET', os.path.join(RD, 'PACKET', 'packet', 'DGP10_QUERY_RESPONSE_PACKET_2026-11-26'))
PRIMARY = ['dg_n64_c2_er50_half', 'dg_n64_c2_clique_half', 'dg_n64_c4_er50_half', 'dg_n64_c4_clique_half', 'dg_n32_c4_er50_half']; STRONG_CONTROLS = ['dg_n64_c4_er50_two', 'dg_n64_c4_clique_two']; FORMER_FRESH = [n + '__eval9' for n in PRIMARY]
ANCHORS_CARD4 = ['dg_n64_c4_er50_half', 'dg_n64_c4_clique_half']; HB_SUCCESS_CELLS = [('dg_n64_c2_er50_half', 0), ('dg_n64_c2_er50_half__eval9', 0), ('dg_n64_c2_er50_half__eval9', 1)]
def sha(p): return hashlib.sha256(open(p, 'rb').read()).hexdigest()
def git(root, *a): return subprocess.check_output(['git', '-C', root] + list(a)).decode().strip()


def archived_dgp9(name):
    """the DGP9 RESULTS table rows of a task: per seed the INCUMBENT / HB_FIXED / HB_REVISED worst radius and completion"""
    R_ = json.load(open(os.path.join(DGP9, 'RESULTS.json'))) if os.path.exists(os.path.join(DGP9, 'RESULTS.json')) else {}; out = {}
    for sub in ('main', 'fresh'):
        for row in (R_.get('tables') or {}).get(sub, []):
            if row['task'] == name: out[str(row['seed_index'])] = {arm: dict(radius=(c or {}).get('worst_radius'), complete=(c or {}).get('complete'), outcome=(c or {}).get('outcome'), seed=(c or {}).get('seed')) for arm, c in (row.get('arms') or {}).items()}
    return out or None


def freeze(root):
    import run_dgp10 as R10, spectral_witness as SW, markov_certificate as MC, heatbath_native as HN, spectral_heatbath_run as SHR, response_certificate as RC
    import numpy, scipy
    commit = git(root, 'rev-parse', 'HEAD'); tree = git(root, 'rev-parse', 'HEAD^{tree}'); dirty = git(root, 'status', '--porcelain', '--untracked-files=no', '--', 'code/cex', 'code/gbidi')
    if dirty: raise SystemExit('dirty checkout: %s' % dirty[:200])
    files = R10.identity(root); harness = ['cex/hp/run_dgp10.py', 'cex/hp/run_dgp9.py', 'cex/hp/run_dgp8.py', 'cex/hp/run_dgp7.py', 'cex/hp/dgp10_manifests.py', 'cex/hp/dgp10_analyze.py', 'cex/hp/dgp10_theory_return.py', 'cex/hp/dgp10_start_here.py', 'cex/hp/dgp10_package.py', 'cex/hp/dgp10_sidecar.py', 'cex/hp/dgp10_oracle.py', 'cex/hp/dgp10_rates.py', 'cex/hp/check_dgp10.py', 'cex/hp/dgp10_probes_layout.py', 'cex/hp/dgp_paths.py', 'cex/hp/validate_round.py', 'cex/hp/check_dgp.py', 'cex/hp/dense_gen.py', 'cex/hp/hp_gen.py']
    hf = {f: (sha(os.path.join(root, 'code', f)) if os.path.exists(os.path.join(root, 'code', f)) else None) for f in harness}
    bud = json.load(open(os.path.join(RD, 'BUDGET_DECLARATION.json'))); prot = sha(os.path.join(RD, 'PROTOCOL.md')); hb_build = os.path.join(root, 'code', 'cex', 'hp', 'heatbath_build.json'); hb_rates = os.path.join(RD, 'HEATBATH_RATES.json'); rr = os.path.join(RD, 'RESPONSE_RATES.json'); inv = os.path.join(RD, 'PACKET', 'NORMATIVE_INVENTORY.json')
    ref_ct = os.path.join(PKT, 'dgp10_theory', 'reference_checked_tilt.py'); ct = os.path.join(root, 'code', 'cex', 'hp', 'checked_tilt.py')
    fr = dict(experiment='DGP10_QUERY_RESPONSE', step='freeze (protocol + code before any scored outcome)', frozen_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), protocol_sha256=prot, brief_sha256=sha(os.path.join(RD, 'PACKET', 'CLAUDE_DGP10_QUERY_RESPONSE_AND_REPAIRS.md')), theory_sha256=sha(os.path.join(RD, 'PACKET', 'DGP10_QUERY_RESPONSE_THEORY_2026-11-26.md')), spec_sha256=sha(os.path.join(PKT, 'dgp10_theory', 'FROZEN_EXPERIMENT_SPEC.md')), packet_zip_sha256='984043e3e15ddd67ec8b222ce1342ff4bdc01309adb4d3ecb13ae1a23d79a291', normative_inventory_sha256=(sha(inv) if os.path.exists(inv) else None),
              harness_files=hf, harness_files_absent_at_freeze=[f for f, h in hf.items() if h is None], arm_identity_files=list(files),
              code=dict(commit=commit, tree=tree, branch='dgp10-query-response', parent='d1932cf1f4475852b1620ba7fe5d0a901809c133 (DGP9 frozen; pinned by the spec)', files=files, runner_version=SHR.VERSION, heatbath_kernel=(json.load(open(hb_build)) if os.path.exists(hb_build) else None), dependencies=dict(python=sys.version.split()[0], numpy=numpy.__version__, scipy=scipy.__version__, platform=platform.platform(), compiler=subprocess.check_output(['clang', '--version']).decode().split('\n')[0])),
              arms=dict(R10.ARM_ARGS, production=list(R10.PRODUCTION_ARMS), diagnostic=list(R10.DIAGNOSTIC_ARMS), rotation=R10.FROZEN['arm_rotation'], seed_rule_exposed=R10.FROZEN['seed_rule_exposed'], seed_rule_fresh=R10.FROZEN['seed_rule_fresh'], select='NOT IMPLEMENTED this round (no selector; standalone results only)'),
              heatbath=dict(witness=SW.PROFILE, native=HN.PROFILE, certificate=MC.PROFILE, runner=dict(reserve_s=SHR.PROFILE['reserve_s'], default_rate_steps_per_s=SHR.PROFILE['default_rate_steps_per_s'], exact_chain_rate_steps_per_s=SHR.PROFILE['exact_chain_rate_steps_per_s'], batch_steps=SHR.PROFILE['batch_steps'], revised=SHR.PROFILE['revised'], publication=SHR.PROFILE['publication'], output_commit=SHR.PROFILE['output_commit']),
                            response=dict(SHR.PROFILE['response'], certificate=RC.PROFILE, local_plan=HN.local_checkpoint_plan(), alphas=[str(a) for a in RC.ALPHAS], checker_sha256=sha(ct), reference_checker_sha256=(sha(ref_ct) if os.path.exists(ref_ct) else None), checker_byte_identical=(os.path.exists(ref_ct) and sha(ref_ct) == sha(ct))),
                            rate_model_hb=(dict(path='HEATBATH_RATES.json', sha256=sha(hb_rates), origin='the exact bytes of DGP9 HEATBATH_RATES.json (frozen before DGP9 scoring; never recalibrated)') if os.path.exists(hb_rates) else 'ABSENT'), rate_model_response=(dict(path='RESPONSE_RATES.json', sha256=sha(rr)) if os.path.exists(rr) else 'NOT YET (written by dgp10_rates.py from the RESPONSE_SCREEN development streams; RESPONSE requires it)')),
              panels=dict(exposed=PRIMARY + STRONG_CONTROLS + FORMER_FRESH, exposed_n=12, fresh='dense_gen eval10 (DGP10/EVAL10/): 5 matched weak + 2 strong twins, generated at holdout', fresh_n=7, preservation=['PRESERVATION_24', 'PRESERVATION_18', 'PRESERVATION_13'], seeds=[0, 1], seed_1_reversed=True, card4_anchors=ANCHORS_CARD4, hb_success_cells=HB_SUCCESS_CELLS),
              gates=dict(validity='D1-D90 + D91-D102 all pass from the clean checkout; the carried probes report the defects ABSENT at the frozen commit (PRESENT on the pinned parent); the packet references pass; the oracle gate PASS; no late row; ledger identity on every heat-bath cell', response_execution='actual conditional observations, local snapshots, checked moment U and mean R execute on both exposed card-4 anchors', material_partial_accuracy='on dg_n64_c4_er50_half AND dg_n64_c4_clique_half, in BOTH seeds, RESPONSE worst radius over the original inventory (timely checked enclosures incl. wider-than-eps; [0,1] -> 0.5 when none) <= 1/2 x HB_R same-round worst radius', completion='every original coordinate epsilon-published with positive mass and a valid receipt in BOTH seeds (exposed / fresh separately; one-seed reported separately)', preservation='INCUMBENT_R 24/24, 18/18, 13/13; RESPONSE keeps every successful DGP9 HB seed-cell (dg_n64_c2_er50_half seed 0; dg_n64_c2_er50_half__eval9 seeds 0 and 1); passing n32 reported across the three arms', cost='mutual completions: flag > 1.25x and > 0.1 s', generalization='fresh separately; strong refusal is not a mixing claim'),
              contracts=R10.CONTRACTS, memory=dict(supervisor_gib=R10.FROZEN['mem_gib'], constructor_bytes=128 << 20), budget=bud)
    json.dump(fr, open(os.path.join(RD, 'FREEZE.json'), 'w'), indent=1, default=str); print(json.dumps(dict(commit=commit[:12], identity_files=len(files), harness_absent=fr['harness_files_absent_at_freeze'], hb_rates=('present' if os.path.exists(hb_rates) else 'absent'), response_rates=('present' if os.path.exists(rr) else 'absent'), checker_identical=fr['heatbath']['response']['checker_byte_identical']))); return fr


def holdout(root):
    import dgp_paths, run_dgp10 as R10
    fr = json.load(open(os.path.join(RD, 'FREEZE.json'))); head = git(root, 'rev-parse', 'HEAD')
    if head != fr['code']['commit']: raise SystemExit('holdout must run at the frozen commit %s (checkout %s)' % (fr['code']['commit'][:12], head[:12]))
    m9 = json.load(open(os.path.join(DGP9, 'MAIN_EXPOSED_MANIFEST.json')))['tasks']; f9 = json.load(open(os.path.join(DGP9, 'FRESH_MANIFEST.json')))['tasks']
    def resolve(t):
        p = dgp_paths.resolve_input(t['model'], DGP9, t.get('model_sha256')); h = sha(p)
        if h != t['model_sha256']: raise SystemExit('input hash mismatch: %s' % t['name'])
        return dict(t, model=p, verified=True)
    exposed = [resolve(dict(t, role=(t.get('role') or 'primary_weak'), origin='dgp9_exposed')) for t in m9] + [resolve(dict(t, role='former_fresh_now_exposed', origin='dgp9_fresh')) for t in f9]
    # the exposed seeds: DGP9's rule, CHECKED against the archived DGP9 cells
    checked = 0
    for t in exposed:
        t['seed_tag'] = 'DGP9-SAMPLE'; t['seeds'] = {str(k): R10.sample_seed(t['model_sha256'], k, 'DGP9-SAMPLE') for k in (0, 1)}; t['archived_dgp9'] = archived_dgp9(t['name'])
        for p in glob.glob(os.path.join(DGP9, 'runs', '*', '*__%s__*' % t['name'].replace('__eval9', ''), 'cell.json')):
            c = json.load(open(p))['cell']
            if c.get('model_sha256') == t['model_sha256']: assert int(c['seed']) == t['seeds'][str(c.get('seed_index', 0))], ('archived seed differs', t['name'], c['seed']); checked += 1
    assert len(exposed) == 12 and checked > 0, (len(exposed), checked)
    fresh_dir = os.path.join(RD, 'inputs', 'fresh'); os.makedirs(fresh_dir, exist_ok=True)
    gen = subprocess.run([sys.executable, os.path.join(root, 'code', 'cex', 'hp', 'dense_gen.py'), 'eval10', fresh_dir], capture_output=True, text=True, timeout=900)
    if gen.returncode != 0: raise SystemExit('fresh generation failed: %s' % gen.stderr[-400:])
    gman = json.load(open(os.path.join(fresh_dir, 'GENERATED_MANIFEST.json'))) if os.path.exists(os.path.join(fresh_dir, 'GENERATED_MANIFEST.json')) else None
    fresh = []
    for p in sorted(glob.glob(os.path.join(fresh_dir, '*.uai'))):
        name = os.path.basename(p)[:-4]; parts = name.split('_'); n = int(parts[1][1:]); card = int(parts[2][1:]); topo = parts[3]; coup = parts[4]; h = sha(p)
        fresh.append(dict(name=name + '__eval10', model=p, model_sha256=h, n=n, card=card, topology=topo, family=topo, coupling=coup, role=('fresh_strong_control' if coup == 'two' else 'fresh_matched_weak'), generator='dense_gen eval10 (DGP10/EVAL10/)', seed_tag='DGP10-SAMPLE', seeds={str(k): R10.sample_seed(h, k, 'DGP10-SAMPLE') for k in (0, 1)}, archived_incumbent=None, archived_dgp9=None))
    assert len(fresh) == 7, len(fresh)
    def pres(fn):
        t_ = json.load(open(os.path.join(DGP9, fn)))['tasks']; out = []
        for t in t_: t = dict(t, role='preservation', seed_tag='DGP9-SAMPLE'); t['seeds'] = {'0': R10.sample_seed(t['model_sha256'], 0, 'DGP9-SAMPLE')}; out.append(resolve(t))
        return out
    p24 = pres('PRESERVATION_24_MANIFEST.json'); p18 = pres('PRESERVATION_18_MANIFEST.json'); p13 = pres('PRESERVATION_13_MANIFEST.json')
    copied = {}
    for panel, tasks in (('exposed', exposed), ('preservation_24', p24), ('preservation_18', p18), ('preservation_13', p13)):
        d = os.path.join(RD, 'inputs', panel); os.makedirs(d, exist_ok=True)
        for t in tasks:
            dst = os.path.join(d, '%s.uai' % t['name']); shutil.copyfile(t['model'], dst)
            if os.path.exists(t['model'] + '.evid'): shutil.copyfile(t['model'] + '.evid', dst + '.evid')
            t['packet_copy'] = os.path.relpath(dst, RD); copied[t['name']] = t['packet_copy']
    for t in fresh: t['packet_copy'] = os.path.relpath(t['model'], RD)
    hbr = os.path.join(DGP9, 'HEATBATH_RATES.json'); dst = os.path.join(RD, 'HEATBATH_RATES.json')
    if not os.path.exists(dst): shutil.copyfile(hbr, dst)
    assert sha(dst) == sha(hbr) == 'bd508154db959e77fe2ae6b8d5d66a94b4eeecad3727422db605a25bd7735049', 'the HB_R rate file must be the exact DGP9 bytes'
    man = dict(utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), code_commit=head, inputs_shipped_in_packet=True, panels=dict(main_exposed=exposed, fresh=fresh, preservation_24=p24, preservation_18=p18, preservation_13=p13), fresh_generation=dict(kind='eval10', tag='DGP10/EVAL10/', manifest=gman, generator_sha256=sha(os.path.join(root, 'code', 'cex', 'hp', 'dense_gen.py'))), exposed_seeds_checked_against_archived_cells=checked, hb_rates_sha256=sha(dst),
               note='exposed = DGP9\'s 7 exposed (5 weak + 2 strong twins) + DGP9\'s 5 former fresh (now exposed; DGP9-SAMPLE seeds reused: the three successful HB seed-cells keep their identity); fresh = 7 new inputs generated AFTER the freeze (DGP10-SAMPLE seeds); preservation = the 24 / 18 / 13 cohorts (INCUMBENT_R)')
    json.dump(man, open(os.path.join(RD, 'MODEL_MANIFEST.json'), 'w'), indent=1, default=str)
    for fn, tasks, panel in (('MAIN_EXPOSED_MANIFEST.json', exposed, 'main_exposed'), ('FRESH_MANIFEST.json', fresh, 'fresh'), ('PRESERVATION_24_MANIFEST.json', p24, 'preservation_24'), ('PRESERVATION_18_MANIFEST.json', p18, 'preservation_18'), ('PRESERVATION_13_MANIFEST.json', p13, 'preservation_13')):
        json.dump(dict(panel=panel, code_commit=head, tasks=tasks), open(os.path.join(RD, fn), 'w'), indent=1, default=str)
    print(json.dumps(dict(exposed=len(exposed), seeds_checked=checked, fresh=[t['name'] for t in fresh], p24=len(p24), p18=len(p18), p13=len(p13), copied=len(copied))))


if __name__ == '__main__':
    import argparse; ap = argparse.ArgumentParser(); ap.add_argument('step', choices=['freeze', 'holdout']); ap.add_argument('--code-root', default='/Users/adis/Workspace/pgm-dgp10'); a = ap.parse_args()
    (freeze if a.step == 'freeze' else holdout)(os.path.abspath(a.code_root))
