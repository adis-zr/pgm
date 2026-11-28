"""DGP2 packaging: IDENTITY.json (commits, trees, source / configuration / native / dependency identities, archive hashes) + CODE zip (git archive of the frozen commit + sidecar) + RESULTS zip (this round's records only, bound to the code zip).
usage: dgp2_package.py"""

# Source-checkout entry point; production imports never traverse research.
if __package__ in (None, ""):
    import sys as _research_sys
    from pathlib import Path as _ResearchPath
    _research_sys.path.insert(0, str(_ResearchPath(__file__).resolve().parents[3]))
from research.bootstrap import activate as _activate_research
_activate_research()
from research.paths import repo_root as _repo_root, runs_root as _runs_root, records_root as _records_root, source_path as _source_path
import os, sys, json, hashlib, subprocess, time, zipfile, platform
RD = str(_runs_root() / 'mdi_2026-10-28/DGP2_REPAIR_AND_DIAGNOSIS'); REC = str(_records_root() or (_repo_root() / "research" / "records")); PGM = str(_repo_root()); W = str(_repo_root().parent)
def sha(p): return hashlib.sha256(open(p, 'rb').read()).hexdigest()
def git(repo, *a): return subprocess.check_output(['git', '-C', repo] + list(a)).decode().strip()
fr = json.load(open(RD + '/FREEZE.json')); commit = fr['code']['commit']; short = commit[:7]; tree = fr['code']['tree']; rec_commit = git(REC, 'rev-parse', 'HEAD'); head_pgm = git(PGM, 'rev-parse', 'HEAD')
code_zip = '%s/DGP2_CODE_2026-11-25_%s.zip' % (W, short); subprocess.check_call(['git', '-C', PGM, 'archive', '--format=zip', '-9', '--prefix=pgm-%s/' % short, '-o', code_zip, commit])
side = dict(commit=commit, tree=tree, zip_sha256=sha(code_zip), bytes=os.path.getsize(code_zip), regenerate='git archive --format=zip -9 --prefix=pgm-%s/ %s' % (short, short), branch='dgp2-repair-diagnosis-2026-11-25', parent='d4a63cc2f16fe88d332b2e184a31b728560db782', later_commits_on_branch=[l for l in git(PGM, 'log', '--oneline', '%s..HEAD' % commit).split('\n') if l], experiment='DGP2_REPAIR_AND_DIAGNOSIS', files=fr['code']['files'], kernel=fr['code']['kernel'], dependencies=fr['code']['dependencies'])
json.dump(side, open(code_zip + '.identity.json', 'w'), indent=1)
members = []
for root, _, fs in os.walk(RD):
    for f in fs:
        p = os.path.join(root, f)
        if '/DGP2_LEDGER.jsonl.owned/' in p or p.endswith('.pyc'): continue
        members.append(p)
members += [REC + '/docs/LEDGER_ADDITIONS_mdi_capacity_2026-11-02.md', REC + '/docs/INFERENCE_RESEARCH_ROUND_PROTOCOL.md', REC + '/docs/CLAIM_LEDGER.md']
arc = {m: ('ledger/' + os.path.basename(m) if m.startswith(REC + '/docs/') else m.replace(REC + '/code/runs/mdi_2026-10-28/', '')) for m in members}
chron = 'pgm-records:\n' + git(REC, 'log', '--oneline', '-16') + '\n\npgm (branch dgp2-repair-diagnosis-2026-11-25):\n' + git(PGM, 'log', '--oneline', '-8')
scope = ('IN: DGP2_REPAIR_AND_DIAGNOSIS/** (PACKET, PROTOCOL, FREEZE, PROOF_TO_CODE, MODEL / RUN / per-panel manifests, oracle/inputs (16 generated models) + oracle/results + oracle/dev, inputs_fresh (8 generated models), controls/ (before probes on d4a63cc, dev iterations, qualification), runs/ (every cell: cell.json with identities, result.json, stdout, stderr), RESULTS / DIAGNOSTICS / CHARGES / IDENTITY / VALIDATION, REPORT / THEORY_RETURN / START_HERE, reproduce.sh, DGP2_LEDGER.jsonl) + the capacity ledger, the standing protocol and the claim ledger.\n'
         'NOT IN: the .owned receipt directories (contents hashed in the ledger receipts), the 28 exposed inputs (DGP1 archive DGP1_RESULTS_2026-11-25_only.zip sha256 de0388f9..., referenced by sha256 in MODEL_MANIFEST), the 18 unified and 13 accepted preservation inputs (earlier archives, referenced by sha256), venvs, the detached checkouts (regenerate from the commits).\n')
res_zip = '%s/DGP2_RESULTS_2026-11-25_only.zip' % W; msha = {arc[m]: dict(bytes=os.path.getsize(m), sha256=sha(m)) for m in members}
rman = dict(experiment='DGP2_REPAIR_AND_DIAGNOSIS', code_zip=os.path.basename(code_zip), code_zip_sha256=side['zip_sha256'], code_commit=commit, code_tree=tree, records_commit=rec_commit, freeze_sha256=sha(RD + '/FREEZE.json'), protocol_sha256=sha(RD + '/PROTOCOL.md'), scope=scope, utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
with zipfile.ZipFile(res_zip, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    for m in sorted(members): z.write(m, arc[m])
    z.writestr('GIT_CHRONOLOGY.txt', chron); z.writestr('ROUND_MANIFEST.json', json.dumps(rman, indent=1)); z.writestr('RESULTS_SCOPE.md', '# Results scope (DGP2)\n\n' + scope); z.writestr('MEMBER_SHA256.json', json.dumps(msha, indent=1))
bad = zipfile.ZipFile(res_zip).testzip(); n = len(zipfile.ZipFile(res_zip).namelist())
ident = dict(experiment='DGP2_REPAIR_AND_DIAGNOSIS', utc=rman['utc'], code=dict(frozen_commit=commit, frozen_tree=tree, repairs_commit='02326d34f9a9ccba4dd73ac4fdeb76a51b0ba9d1', parent='d4a63cc2f16fe88d332b2e184a31b728560db782', branch='dgp2-repair-diagnosis-2026-11-25', pgm_head_at_packaging=head_pgm, files=fr['code']['files'], kernel=fr['code']['kernel'], dependencies=fr['code']['dependencies'], accepted_engine='v2.13.2 at pgm 1da6da3 (blockres + newarm byte-identical; validate_round check)'), records=dict(commit=rec_commit, first_freeze='9cc7c08d9', second_freeze='2da1d583a', holdout='8b6ada82c'), archives=dict(code_zip=dict(path='~/Workspace/' + os.path.basename(code_zip), sha256=side['zip_sha256'], bytes=side['bytes'], sidecar=os.path.basename(code_zip) + '.identity.json'), results_zip=dict(path='~/Workspace/' + os.path.basename(res_zip), sha256=sha(res_zip), bytes=os.path.getsize(res_zip), members=n, testzip_clean=(bad is None))), host=dict(platform=platform.platform(), machine=platform.machine()), packaging_charge='unsupervised, not computational, not charged')
json.dump(ident, open(RD + '/IDENTITY.json', 'w'), indent=1); print(json.dumps(ident['archives'], indent=1))
