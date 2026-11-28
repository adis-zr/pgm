"""DGP9 packaging (derived from dgp8_package.py; review RV8 / RPA2 repaired): IDENTITY_EXTERNAL.json is written OUTSIDE the results zip (next to it in the archive directory AND copied into the records directory, excluded from any later
zip) and attests the FINAL archives by hash; the results zip carries the EXECUTED harness snapshot with a SELF-CONTAINED git bundle (every commit of the branch) whose restoration into an empty directory is TESTED here, the exact
bytes of EVERY manifest input (inputs/; review RV7) and the whole records tree; the CODE zip is a git archive of the frozen commit with its identity sidecar. The internal IDENTITY.json is kept for continuity but is NOT the
attestation (it necessarily predates the zip that contains it). usage: dgp9_package.py (env DGP9_RD, DGP9_PGM, DGP9_ARCHIVE_DIR)"""

# Source-checkout entry point; production imports never traverse research.
if __package__ in (None, ""):
    import sys as _research_sys
    from pathlib import Path as _ResearchPath
    _research_sys.path.insert(0, str(_ResearchPath(__file__).resolve().parents[3]))
from research.bootstrap import activate as _activate_research
_activate_research()
from research.paths import repo_root as _repo_root, runs_root as _runs_root, records_root as _records_root, source_path as _source_path
import os, sys, json, hashlib, subprocess, time, zipfile, platform, shutil, tempfile, glob
RD = os.environ.get('DGP9_RD', str(_runs_root() / 'mdi_2026-10-28/DGP9_SPECTRAL_HEATBATH_CONTINUATION')); REC = os.environ.get('DGP9_REC', str(_records_root() or (_repo_root() / "research" / "records"))); PGM = os.environ.get('DGP9_PGM', str(_repo_root())); W = os.environ.get('DGP9_ARCHIVE_DIR', str(_repo_root().parent)); BRANCH = 'dgp9-heatbath-continuation'
def sha(p): return hashlib.sha256(open(p, 'rb').read()).hexdigest()
def git(repo, *a): return subprocess.check_output(['git', '-C', repo] + list(a)).decode().strip()
fr = json.load(open(RD + '/FREEZE.json')); commit = fr['code']['commit']; short = commit[:7]; tree = fr['code']['tree']; rec_commit = git(REC, 'rev-parse', 'HEAD'); head_pgm = git(PGM, 'rev-parse', 'HEAD')
code_zip = '%s/DGP9_CODE_2026-11-27_%s.zip' % (W, short); subprocess.check_call(['git', '-C', PGM, 'archive', '--format=zip', '-9', '--prefix=pgm-%s/' % short, '-o', code_zip, commit])
side = dict(commit=commit, tree=tree, zip_sha256=sha(code_zip), bytes=os.path.getsize(code_zip), regenerate='git archive --format=zip -9 --prefix=pgm-%s/ %s' % (short, short), branch=BRANCH, parent='ebf994c (the dgp8-spectral-heatbath tip; the DGP8 engine ad20e73 + two harness amendments)', later_commits_on_branch=[l for l in git(PGM, 'log', '--oneline', '%s..HEAD' % commit).split('\n') if l], experiment='DGP9_SPECTRAL_HEATBATH_CONTINUATION', files=fr['code']['files'], utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
json.dump(side, open(code_zip + '.identity.json', 'w'), indent=1)
HARNESS = ['research/campaigns/hp/run_dgp9.py', 'research/campaigns/hp/run_dgp8.py', 'research/campaigns/hp/run_dgp7.py', 'research/campaigns/hp/dgp9_manifests.py', 'research/campaigns/hp/dgp9_analyze.py', 'research/campaigns/hp/dgp9_theory_return.py', 'research/campaigns/hp/dgp9_start_here.py', 'research/campaigns/hp/dgp9_package.py', 'research/campaigns/hp/dgp9_sidecar.py', 'research/campaigns/hp/dgp9_probes.py', 'research/campaigns/hp/dgp9_rates.py', 'src/pgm/algorithms/response/spectral_heatbath_run.py', 'src/pgm/algorithms/response/spectral_witness.py', 'src/pgm/algorithms/response/heatbath_exact.py', 'src/pgm/algorithms/response/heatbath_native.c', 'src/pgm/algorithms/response/heatbath_native.py', 'src/pgm/algorithms/response/markov_certificate.py', 'src/pgm/algorithms/response/heatbath_build.json', 'research/campaigns/hp/dgp_paths.py', 'research/campaigns/hp/validate_round.py', 'research/campaigns/hp/check_dgp.py', 'research/campaigns/hp/dense_gen.py', 'research/campaigns/hp/hp_gen.py', 'src/pgm/algorithms/quotient/unified_pac_planner.py', 'src/pgm/algorithms/quotient/pac_actions.py', 'src/pgm/algorithms/quotient/coarse_envelope.py']
hs = RD + '/harness'; os.makedirs(hs + '/files', exist_ok=True); bundle = '%s/pgm-%s.bundle' % (hs, BRANCH)
subprocess.check_call(['git', '-C', PGM, 'bundle', 'create', bundle, BRANCH, 'HEAD']); subprocess.check_call(['git', '-C', PGM, 'bundle', 'verify', bundle], stdout=subprocess.DEVNULL)
tmp = tempfile.mkdtemp(prefix='dgp9_restore_'); subprocess.check_call(['git', 'clone', '-q', bundle, tmp + '/pgm-restored']); subprocess.check_call(['git', '-C', tmp + '/pgm-restored', 'checkout', '-q', '--detach', commit])
restored = {f: sha(os.path.join(tmp, 'pgm-restored', 'code', f)) for f in fr['code']['files']}; restore_ok = (restored == fr['code']['files']); amend_ok = {}
for a_ in sorted(glob.glob(RD + '/FREEZE_AMENDMENT_*.json')):
    aj = json.load(open(a_)); c_ = (aj.get('code') or {}).get('commit') or aj.get('amendment_commit')
    if c_:
        subprocess.check_call(['git', '-C', tmp + '/pgm-restored', 'checkout', '-q', '--detach', c_]); files_ = (aj.get('code') or {}).get('files') or {f: v['amended'] for f, v in (aj.get('files_changed') or {}).items()}
        amend_ok[os.path.basename(a_)] = all(sha(os.path.join(tmp, 'pgm-restored', 'code', f)) == h for f, h in files_.items())
subprocess.check_call(['git', '-C', tmp + '/pgm-restored', 'checkout', '-q', '--detach', commit]); shutil.rmtree(tmp, ignore_errors=True)
exec_src = {}
for f in HARNESS:
    live = os.path.join(PGM, 'code', f)
    if not os.path.exists(live): continue
    shutil.copyfile(live, os.path.join(hs, 'files', os.path.basename(f))); exec_src[f] = sha(live)
frozen_files = fr['code']['files']; diff_vs_frozen = {f: dict(frozen=frozen_files.get(f), executed=h) for f, h in exec_src.items() if frozen_files.get(f) not in (None, h)}; not_in_freeze = [f for f in exec_src if f not in frozen_files]
json.dump(dict(restoration_test=dict(ok=restore_ok and all(amend_ok.values()), frozen_ok=restore_ok, amendments_ok=amend_ok, method='git clone <bundle> into an empty temp dir; git checkout --detach <frozen commit> and each FREEZE_AMENDMENT commit (both schemas); sha256 of every recorded identity / amended file compared', frozen_commit=commit), pgm_head_at_packaging=head_pgm, frozen_commit=commit, bundle=os.path.basename(bundle), bundle_sha256=sha(bundle), files=exec_src, diff_vs_frozen=diff_vs_frozen, not_in_freeze=dict(files=not_in_freeze, note='harness / writers outside the arm identity (their executed hashes are above)'), utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())), open(hs + '/EXECUTED_HARNESS_SHA256.json', 'w'), indent=1)
members = []
for root, _, fs in os.walk(RD):
    for f in fs:
        p = os.path.join(root, f)
        if '/DGP9_LEDGER.jsonl.owned/' in p or p.endswith('.pyc') or '/restored/' in p or '/replay/' in p or '/review_evidence/' in p or f == 'IDENTITY_EXTERNAL.json' or '/reproduce_test/replay' in p: continue      # the unpacked review tree is reproducible from PACKET/*.zip; the EXTERNAL identity manifest is never a member of the zip it attests
        members.append(p)
members += [REC + '/docs/LEDGER_ADDITIONS_mdi_capacity_2026-11-02.md', REC + '/docs/INFERENCE_RESEARCH_ROUND_PROTOCOL.md', REC + '/docs/CLAIM_LEDGER.md']
arc = {m: ('ledger/' + os.path.basename(m) if m.startswith(REC + '/docs/') else m.replace(REC + '/code/runs/mdi_2026-10-28/', '')) for m in members}
chron = 'pgm-records:\n' + git(REC, 'log', '--oneline', '-16') + '\n\npgm (branch %s):\n' % BRANCH + git(PGM, 'log', '--oneline', '-12')
scope = ('IN: DGP9_SPECTRAL_HEATBATH_CONTINUATION/** (PACKET (brief, review, evidence zip + hashes; NORMATIVE_INVENTORY), PROTOCOL, FREEZE (+ amendments), PROOF_TO_CODE, REPAIR_TABLE, MODEL / RUN / per-panel manifests, inputs/ (the exact bytes of every manifest input), HEATBATH_RATES, controls/ (before probes on the pinned parent, dev, qualification + after probes), runs/ (every cell), harness/ (executed files + the self-contained bundle), RESULTS / DIAGNOSTICS / CHARGES / IDENTITY / VALIDATION, REPORT / THEORY_RETURN / START_HERE / ERRATA_DGP8, reproduce.sh / RESTORE_TEST.sh, DGP9_LEDGER.jsonl + the sidecar) + the capacity ledger, the standing protocol and the claim ledger.\n'
         'NOT IN: the unpacked review_evidence tree (reproducible from PACKET/DGP8_INDEPENDENT_REVIEW_EVIDENCE_2026-11-26.zip via its bootstrap), the .owned receipt directories, venvs, the detached checkouts (regenerate from the bundle), IDENTITY_EXTERNAL.json (OUTSIDE this zip by construction).\n')
res_zip = '%s/DGP9_RESULTS_2026-11-27_only.zip' % W; msha = {arc[m]: dict(bytes=os.path.getsize(m), sha256=sha(m)) for m in members}
rman = dict(experiment='DGP9_SPECTRAL_HEATBATH_CONTINUATION', harness_bundle=dict(path=os.path.relpath(bundle, RD), sha256=sha(bundle), bytes=os.path.getsize(bundle), self_contained=True, restoration_test_ok=(restore_ok and all(amend_ok.values())), amendment_commits_restore=amend_ok), code_zip=os.path.basename(code_zip), code_zip_sha256=side['zip_sha256'], code_commit=commit, code_tree=tree, records_commit=rec_commit, freeze_sha256=sha(RD + '/FREEZE.json'), protocol_sha256=sha(RD + '/PROTOCOL.md'), scope=scope, utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
ident_int = dict(experiment='DGP9_SPECTRAL_HEATBATH_CONTINUATION', utc=rman['utc'], note='INTERNAL identity (predates the zip that contains it; the attestation is IDENTITY_EXTERNAL.json next to the archives)', code=dict(frozen_commit=commit, frozen_tree=tree, parent=side['parent'], branch=BRANCH, pgm_head_at_packaging=head_pgm, files=fr['code']['files'], dependencies=fr['code'].get('dependencies'), accepted_engine='v2.13.2 at pgm 1da6da3 (byte-identical; validate_round check); this branch is NOT merged into the default'), records=dict(commit=rec_commit), harness_bundle=rman['harness_bundle'], code_zip=dict(path='~/Workspace/' + os.path.basename(code_zip), sha256=side['zip_sha256'], bytes=side['bytes']), host=dict(platform=platform.platform(), machine=platform.machine()))
json.dump(ident_int, open(RD + '/IDENTITY.json', 'w'), indent=1); members.append(RD + '/IDENTITY.json'); arc[RD + '/IDENTITY.json'] = 'DGP9_SPECTRAL_HEATBATH_CONTINUATION/IDENTITY.json'; msha[arc[RD + '/IDENTITY.json']] = dict(bytes=os.path.getsize(RD + '/IDENTITY.json'), sha256=sha(RD + '/IDENTITY.json'))
members = sorted(set(members))
with zipfile.ZipFile(res_zip, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    for m in members: z.write(m, arc[m])
    z.writestr('GIT_CHRONOLOGY.txt', chron); z.writestr('ROUND_MANIFEST.json', json.dumps(rman, indent=1)); z.writestr('RESULTS_SCOPE.md', '# Results scope (DGP9)\n\n' + scope); z.writestr('MEMBER_SHA256.json', json.dumps(msha, indent=1))
bad = zipfile.ZipFile(res_zip).testzip(); n = len(zipfile.ZipFile(res_zip).namelist())
ext = dict(experiment='DGP9_SPECTRAL_HEATBATH_CONTINUATION', kind='EXTERNAL final archive identity manifest (written after both archives were closed; never a member of the results zip)', utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), archives=dict(code_zip=dict(path='~/Workspace/' + os.path.basename(code_zip), sha256=side['zip_sha256'], bytes=side['bytes'], sidecar=os.path.basename(code_zip) + '.identity.json'), results_zip=dict(path='~/Workspace/' + os.path.basename(res_zip), sha256=sha(res_zip), bytes=os.path.getsize(res_zip), members=n, testzip_clean=(bad is None))),
           harness_bundle=rman['harness_bundle'], code=dict(frozen_commit=commit, frozen_tree=tree, branch=BRANCH, pgm_head_at_packaging=head_pgm), records_commit_at_packaging=rec_commit, host=dict(platform=platform.platform(), machine=platform.machine()), packaging_charge='charged under scope dgp9_analysis (gbidi.supervise receipt dgp9:packaging:package*)')
json.dump(ext, open(res_zip + '.identity.json', 'w'), indent=1); json.dump(ext, open(RD + '/IDENTITY_EXTERNAL.json', 'w'), indent=1)
print(json.dumps(dict(archives=ext['archives'], bundle=rman['harness_bundle'], diff_vs_frozen=sorted(diff_vs_frozen)), indent=1))
