"""Two-archive packaging of DENSE_GENERIC_PAC_INTEGRATION_1 (CODE = git archive of the reviewed pgm commit + identity sidecar; RESULTS = this experiment's records only, bound to the code zip). usage: dgp_package.py"""

# Source-checkout entry point; production imports never traverse research.
if __package__ in (None, ""):
    import sys as _research_sys
    from pathlib import Path as _ResearchPath
    _research_sys.path.insert(0, str(_ResearchPath(__file__).resolve().parents[3]))
from research.bootstrap import activate as _activate_research
_activate_research()
from research.paths import repo_root as _repo_root, runs_root as _runs_root, records_root as _records_root, source_path as _source_path
import os, sys, json, hashlib, subprocess, time, zipfile
RD = str(_runs_root() / 'mdi_2026-10-28/DENSE_GENERIC_PAC_INTEGRATION_1'); REC = str(_records_root() or (_repo_root() / "research" / "records")); PGM = str(_repo_root()); W = str(_repo_root().parent)
def sha(p): return hashlib.sha256(open(p, 'rb').read()).hexdigest()
def git(repo, *a): return subprocess.check_output(['git', '-C', repo] + list(a)).decode().strip()
head = git(PGM, 'rev-parse', 'HEAD'); short = head[:7]; tree = git(PGM, 'rev-parse', 'HEAD^{tree}'); rec_commit = git(REC, 'rev-parse', 'HEAD')
code_zip = '%s/DGP1_CODE_2026-11-25_%s.zip' % (W, short); subprocess.check_call(['git', '-C', PGM, 'archive', '--format=zip', '-9', '--prefix=pgm-%s/' % short, '-o', code_zip, head])
fr = json.load(open(RD + '/EVALUATION_FREEZE.json')); am = json.load(open(RD + '/FREEZE_AMENDMENT_1.json'))
files = {f: sha(os.path.join(PGM, 'code', f)) for f in fr['code']['files']}
side = dict(commit=head, tree=tree, zip_sha256=sha(code_zip), bytes=os.path.getsize(code_zip), regenerate='git archive --format=zip -9 --prefix=pgm-%s/ %s' % (short, short), frozen_commit=fr['code']['commit'], repaired_commit=am['repaired_code'], accepted_engine='v2.13.2 at pgm 1da6da3 (blockres byte-identical)', files=files, experiment='DENSE_GENERIC_PAC_INTEGRATION_1')
json.dump(side, open(code_zip + '.identity.json', 'w'), indent=1)
members = []
for root, _, fs in os.walk(RD):
    for f in fs:
        p = os.path.join(root, f)
        if '/DGP_LEDGER.jsonl.owned/' in p: continue
        members.append(p)
members.append(REC + '/docs/LEDGER_ADDITIONS_mdi_capacity_2026-11-02.md')
arc = {m: ('ledger/' + os.path.basename(m) if m.startswith(REC + '/docs/') else m.replace(REC + '/code/runs/mdi_2026-10-28/', '')) for m in members}
chron = 'pgm-records:\n' + git(REC, 'log', '--oneline', '-12') + '\n\npgm:\n' + git(PGM, 'log', '--oneline', '-10')
scope = ('IN: DENSE_GENERIC_PAC_INTEGRATION_1/** (PACKET + brief, BUDGET_DECLARATION, EVALUATION_FREEZE, FREEZE_AMENDMENT_1, MAIN / LONG / PRESERVATION / CONFIRM manifests, inputs_eval (24 holdout models + GENERATED_MANIFEST), external (census + selection), dev (dev inputs, control iterations, smokes, unsupervised log), qualification (all suites, both builds), main (frozen v0.5, 112 cells), main_v051 (56 cells), preservation_18 / _13 (frozen) + _v051, confirm, long, ANALYSIS / ANALYSIS_frozen_v05 / RESULTS.md, DGP_LEDGER.jsonl) + the capacity ledger (E-MDI-50).\n'
         'NOT IN: the .owned receipt directories (hashes of their contents are in the ledger receipts), the 18 unified inputs (UNIFIED_PLANNER / HP_COMPILER archives, referenced by sha256 in the manifests), the 13 exposed external inputs (EXTERNAL_SWEEP / BLOCKRES archives, referenced by sha256), earlier experiments, venvs.\n')
res_zip = '%s/DGP1_RESULTS_2026-11-25_only.zip' % W; msha = {arc[m]: dict(bytes=os.path.getsize(m), sha256=sha(m)) for m in members}
rman = dict(experiment='DENSE_GENERIC_PAC_INTEGRATION_1', code_zip=os.path.basename(code_zip), code_zip_sha256=side['zip_sha256'], code_commit='%s (frozen %s; repaired %s)' % (short, fr['code']['commit'][:9], am['repaired_code']), records_commit=rec_commit, freeze_sha256=sha(RD + '/EVALUATION_FREEZE.json'), amendment_sha256=sha(RD + '/FREEZE_AMENDMENT_1.json'), scope=scope, utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
with zipfile.ZipFile(res_zip, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    for m in sorted(members): z.write(m, arc[m])
    z.writestr('GIT_CHRONOLOGY.txt', chron); z.writestr('ROUND_MANIFEST.json', json.dumps(rman, indent=1)); z.writestr('RESULTS_SCOPE.md', '# Results scope (DENSE_GENERIC_PAC_INTEGRATION_1)\n\n' + scope); z.writestr('MEMBER_SHA256.json', json.dumps(msha, indent=1))
bad = zipfile.ZipFile(res_zip).testzip(); n = len(zipfile.ZipFile(res_zip).namelist())
pkg = dict(experiment='DENSE_GENERIC_PAC_INTEGRATION_1', code_commit=short, frozen_commit=fr['code']['commit'][:9], repaired_commit=am['repaired_code'], accepted_engine='v2.13.2 at pgm 1da6da3 (unchanged)', records_commit_before_packaging=rec_commit, code_zip=dict(path='~/Workspace/' + os.path.basename(code_zip), sha256=side['zip_sha256'], bytes=side['bytes'], identity_sidecar=os.path.basename(code_zip) + '.identity.json'), results_zip=dict(path='~/Workspace/' + os.path.basename(res_zip), sha256=sha(res_zip), bytes=os.path.getsize(res_zip), members=n, testzip_clean=(bad is None)), packaging_charge_note='unsupervised; not a computational run; not charged', utc=rman['utc'])
json.dump(pkg, open(RD + '/PACKAGE_RECORD_dgp1.json', 'w'), indent=1); print(json.dumps(pkg, indent=1))
