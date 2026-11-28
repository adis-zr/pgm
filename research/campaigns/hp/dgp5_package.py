"""DGP5 packaging (derived from dgp3_package.py): IDENTITY.json + CODE zip (git archive of the frozen commit + sidecar) + RESULTS zip + the EXECUTED harness snapshot with a SELF-CONTAINED git bundle (every object of the branch; no prerequisite commits) whose restoration into an empty directory is TESTED here (clone, checkout of the frozen commit, arm-file hash verification): IDENTITY.json (commits, trees, source / configuration / native / dependency identities, archive hashes) + CODE zip (git archive of the frozen commit + sidecar) + RESULTS zip (this round's records only, bound to the code zip).
usage: dgp5_package.py"""

# Source-checkout entry point; production imports never traverse research.
if __package__ in (None, ""):
    import sys as _research_sys
    from pathlib import Path as _ResearchPath
    _research_sys.path.insert(0, str(_ResearchPath(__file__).resolve().parents[3]))
from research.bootstrap import activate as _activate_research
_activate_research()
from research.paths import repo_root as _repo_root, runs_root as _runs_root, records_root as _records_root, source_path as _source_path
import os, sys, json, hashlib, subprocess, time, zipfile, platform
RD = str(_runs_root() / 'mdi_2026-10-28/DGP5_JOINT_CONSTRUCTION'); REC = str(_records_root() or (_repo_root() / "research" / "records")); PGM = str(_repo_root()); W = os.environ.get('DGP5_ARCHIVE_DIR', str(_repo_root().parent))
def sha(p): return hashlib.sha256(open(p, 'rb').read()).hexdigest()
def git(repo, *a): return subprocess.check_output(['git', '-C', repo] + list(a)).decode().strip()
fr = json.load(open(RD + '/FREEZE.json')); commit = fr['code']['commit']; short = commit[:7]; tree = fr['code']['tree']; rec_commit = git(REC, 'rev-parse', 'HEAD'); head_pgm = git(PGM, 'rev-parse', 'HEAD')
code_zip = '%s/DGP5_CODE_2026-11-26_%s.zip' % (W, short); subprocess.check_call(['git', '-C', PGM, 'archive', '--format=zip', '-9', '--prefix=pgm-%s/' % short, '-o', code_zip, commit])
side = dict(commit=commit, tree=tree, zip_sha256=sha(code_zip), bytes=os.path.getsize(code_zip), regenerate='git archive --format=zip -9 --prefix=pgm-%s/ %s' % (short, short), branch='dgp5-joint-construction', parent='ffa73caa5737d56cf42c1f3640230ac553d7c64e', later_commits_on_branch=[l for l in git(PGM, 'log', '--oneline', '%s..HEAD' % commit).split('\n') if l], experiment='DGP5_JOINT_CONSTRUCTION', files=fr['code']['files'], kernel=fr['code']['kernel'], dependencies=fr['code']['dependencies'])
json.dump(side, open(code_zip + '.identity.json', 'w'), indent=1)
# ---- EXECUTED harness snapshot (DGP2 review, packaging finding): a git bundle of the branch and copies of the executed harness / analyzer / oracle files (from the checkout recorded in the cells, or the live tree for files executed there) with hashes
HARNESS = ['research/campaigns/hp/run_dgp5.py', 'research/campaigns/hp/dgp5_oracle.py', 'research/campaigns/hp/dgp2_oracle.py', 'research/campaigns/hp/dgp3_oracle.py', 'research/campaigns/hp/dgp5_oracle_driver.py', 'research/campaigns/hp/dgp5_analyze.py', 'research/campaigns/hp/dgp5_manifests.py', 'research/campaigns/hp/dgp5_probes.py', 'research/campaigns/hp/validate_round.py', 'research/campaigns/hp/dgp5_package.py', 'research/campaigns/hp/dgp5_start_here.py', 'research/campaigns/hp/dgp5_theory_return.py', 'research/campaigns/hp/dense_gen.py', 'research/campaigns/hp/check_dgp.py', 'src/pgm/algorithms/quotient/check_joint.py', 'research/campaigns/hp/hp_gen.py', 'src/pgm/runtime/supervise.py']
hs = RD + '/harness'; os.makedirs(hs + '/files', exist_ok=True); bundle = '%s/pgm-dgp5-joint-construction.bundle' % hs
subprocess.check_call(['git', '-C', PGM, 'bundle', 'create', bundle, 'dgp5-joint-construction', 'HEAD']); subprocess.check_call(['git', '-C', PGM, 'bundle', 'verify', bundle], stdout=subprocess.DEVNULL)          # SELF-CONTAINED: the whole history of the branch (no ^prerequisite)
# restoration test in an EMPTY directory: clone the bundle, check out the frozen commit, verify every arm identity file against FREEZE.json
import tempfile; tmp = tempfile.mkdtemp(prefix='dgp5_restore_'); subprocess.check_call(['git', 'clone', '-q', bundle, tmp + '/pgm-restored']); subprocess.check_call(['git', '-C', tmp + '/pgm-restored', 'checkout', '-q', '--detach', commit])
restored = {f: sha(os.path.join(tmp, 'pgm-restored', 'code', f)) for f in fr['code']['files']}; restore_ok = (restored == fr['code']['files']); amend_ok = {}
import glob as _glob
for a_ in sorted(_glob.glob(RD + '/FREEZE_AMENDMENT_*.json')):                                   # every amendment commit restores from the SAME bundle with its recorded identity files
    aj = json.load(open(a_))
    if aj.get('code', {}).get('commit'):
        subprocess.check_call(['git', '-C', tmp + '/pgm-restored', 'checkout', '-q', '--detach', aj['code']['commit']]); amend_ok[os.path.basename(a_)] = ({f: sha(os.path.join(tmp, 'pgm-restored', 'code', f)) for f in aj['code']['files']} == aj['code']['files'])
subprocess.check_call(['git', '-C', tmp + '/pgm-restored', 'checkout', '-q', '--detach', commit]); shutil_rm = __import__('shutil').rmtree(tmp, ignore_errors=True)
exec_src = {}
for f in HARNESS:
    live = os.path.join(PGM, 'code', f)
    if not os.path.exists(live): continue
    import shutil; shutil.copyfile(live, os.path.join(hs, 'files', os.path.basename(f))); exec_src[f] = sha(live)
frozen_files = fr['code']['files']; diff_vs_frozen = {f: dict(frozen=frozen_files.get(f), executed=h) for f, h in exec_src.items() if frozen_files.get(f) not in (None, h)}; not_in_freeze = [f for f in exec_src if f not in frozen_files]
json.dump(dict(restoration_test=dict(ok=restore_ok and all(amend_ok.values()), frozen_ok=restore_ok, amendments_ok=amend_ok, method='git clone <bundle> into an empty temp dir; git checkout --detach <frozen commit> and each FREEZE_AMENDMENT commit; sha256 of every recorded identity file compared', frozen_commit=commit), note='the harness / analyzer / oracle files AS EXECUTED for this round (copies in harness/files, sha256 here); the frozen hashes are in FREEZE.json; any difference is listed in diff_vs_frozen with its FREEZE_AMENDMENT; the bundle carries every commit of the branch (git clone <bundle> -b dgp5-joint-construction)', pgm_head_at_packaging=head_pgm, frozen_commit=commit, bundle=os.path.basename(bundle), bundle_sha256=sha(bundle), files=exec_src, diff_vs_frozen=diff_vs_frozen, not_in_freeze=dict(files=not_in_freeze, note='analysis / packaging writers added after the freeze (no evaluation cell depends on them); their executed hashes are above'), utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())), open(hs + '/EXECUTED_HARNESS_SHA256.json', 'w'), indent=1)
members = []
for root, _, fs in os.walk(RD):
    for f in fs:
        p = os.path.join(root, f)
        if '/DGP5_LEDGER.jsonl.owned/' in p or p.endswith('.pyc') or '/review_layout/' in p or '/restored/' in p or '/replay/' in p: continue        # DGP5 review section 6: the self-contained bundle ships INSIDE the results zip (harness/*.bundle)
        members.append(p)
members += [REC + '/docs/LEDGER_ADDITIONS_mdi_capacity_2026-11-02.md', REC + '/docs/INFERENCE_RESEARCH_ROUND_PROTOCOL.md', REC + '/docs/CLAIM_LEDGER.md']
arc = {m: ('ledger/' + os.path.basename(m) if m.startswith(REC + '/docs/') else m.replace(REC + '/code/runs/mdi_2026-10-28/', '')) for m in members}
chron = 'pgm-records:\n' + git(REC, 'log', '--oneline', '-16') + '\n\npgm (branch dgp5-joint-construction):\n' + git(PGM, 'log', '--oneline', '-12')
scope = ('IN: DGP5_JOINT_CONSTRUCTION/** (PACKET (theory note, brief, standing protocol), PROTOCOL, FREEZE, PROOF_TO_CODE, MODEL / RUN / per-panel manifests, inputs_fresh (8 EVAL5 models) + oracle/inputs_fresh (4 ORACLE5 models), oracle/results + oracle/dev, controls/ (before probes of the six findings on 9355663, dev iterations + e2e cells, qualification incl. the staged control fixtures, after probes at the frozen commit, UNSUPERVISED_DEV_LOG), runs/ (every cell: cell.json with identities, result.json, stdout, stderr), harness/ (EXECUTED runner / analyzer / oracle / probe files with hashes + the SELF-CONTAINED git bundle itself), RESULTS / DIAGNOSTICS / CHARGES / IDENTITY / VALIDATION, REPORT / THEORY_RETURN / START_HERE, reproduce.sh, DGP5_LEDGER.jsonl) + the capacity ledger, the standing protocol and the claim ledger.\n'
         'NOT IN: the .owned receipt directories (contents hashed in the ledger receipts), the 52 exposed main inputs (DGP1-DGP4 archives, referenced by sha256 in MODEL_MANIFEST), the 24 exposed oracle inputs (DGP2 / DGP4 archives), the preservation inputs (earlier archives), venvs, the detached checkouts (regenerate from the bundle).\n')
res_zip = '%s/DGP5_RESULTS_2026-11-26_only.zip' % W; msha = {arc[m]: dict(bytes=os.path.getsize(m), sha256=sha(m)) for m in members}
rman = dict(experiment='DGP5_JOINT_CONSTRUCTION', harness_bundle=dict(path=os.path.relpath(bundle, RD), sha256=sha(bundle), bytes=os.path.getsize(bundle), self_contained=True, restoration_test_ok=(restore_ok and all(amend_ok.values())), amendment_commits_restore=amend_ok), code_zip=os.path.basename(code_zip), code_zip_sha256=side['zip_sha256'], code_commit=commit, code_tree=tree, records_commit=rec_commit, freeze_sha256=sha(RD + '/FREEZE.json'), protocol_sha256=sha(RD + '/PROTOCOL.md'), scope=scope, utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
with zipfile.ZipFile(res_zip, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    for m in sorted(members): z.write(m, arc[m])
    z.writestr('GIT_CHRONOLOGY.txt', chron); z.writestr('ROUND_MANIFEST.json', json.dumps(rman, indent=1)); z.writestr('RESULTS_SCOPE.md', '# Results scope (DGP5)\n\n' + scope); z.writestr('MEMBER_SHA256.json', json.dumps(msha, indent=1))
bad = zipfile.ZipFile(res_zip).testzip(); n = len(zipfile.ZipFile(res_zip).namelist())
ident = dict(experiment='DGP5_JOINT_CONSTRUCTION', utc=rman['utc'], code=dict(frozen_commit=commit, frozen_tree=tree, parent='ffa73caa5737d56cf42c1f3640230ac553d7c64e (the corrected DGP4 closeout head)', branch='dgp5-joint-construction', pgm_head_at_packaging=head_pgm, files=fr['code']['files'], kernel=fr['code']['kernel'], dependencies=fr['code']['dependencies'], accepted_engine='v2.13.2 at pgm 1da6da3 (blockres + newarm byte-identical; validate_round check)'), records=dict(commit=rec_commit, first_freeze=(json.load(open(RD + '/FREEZE_RECORDS_COMMITS.json')) if os.path.exists(RD + '/FREEZE_RECORDS_COMMITS.json') else {}).get('first_freeze'), second_freeze=(json.load(open(RD + '/FREEZE_RECORDS_COMMITS.json')) if os.path.exists(RD + '/FREEZE_RECORDS_COMMITS.json') else {}).get('second_freeze'), holdout=(json.load(open(RD + '/FREEZE_RECORDS_COMMITS.json')) if os.path.exists(RD + '/FREEZE_RECORDS_COMMITS.json') else {}).get('holdout')), archives=dict(code_zip=dict(path='~/Workspace/' + os.path.basename(code_zip), sha256=side['zip_sha256'], bytes=side['bytes'], sidecar=os.path.basename(code_zip) + '.identity.json'), results_zip=dict(path='~/Workspace/' + os.path.basename(res_zip), sha256=sha(res_zip), bytes=os.path.getsize(res_zip), members=n, testzip_clean=(bad is None))), host=dict(platform=platform.platform(), machine=platform.machine()), packaging_charge='charged under scope dgp5_analysis (gbidi.supervise receipt)')
ident['harness_bundle'] = rman['harness_bundle']; json.dump(ident, open(RD + '/IDENTITY.json', 'w'), indent=1); print(json.dumps(dict(archives=ident['archives'], bundle=rman['harness_bundle']), indent=1))
