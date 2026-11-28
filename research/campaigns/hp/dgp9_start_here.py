"""DGP9 START_HERE writer: the one-page entry to the records (what this round is, the five gates, the files, how to reproduce, what is not claimed). usage: dgp9_start_here.py"""

# Source-checkout entry point; production imports never traverse research.
if __package__ in (None, ""):
    import sys as _research_sys
    from pathlib import Path as _ResearchPath
    _research_sys.path.insert(0, str(_ResearchPath(__file__).resolve().parents[3]))
from research.bootstrap import activate as _activate_research
_activate_research()
from research.paths import repo_root as _repo_root, runs_root as _runs_root, records_root as _records_root, source_path as _source_path
import json, os, glob
RD = os.environ.get('DGP9_RD', str(_runs_root() / 'mdi_2026-10-28/DGP9_SPECTRAL_HEATBATH_CONTINUATION'))
R = json.load(open(RD + '/RESULTS.json')); G = R['gates']; fr = json.load(open(RD + '/FREEZE.json')) if os.path.exists(RD + '/FREEZE.json') else {'code': {}}; ident = json.load(open(RD + '/IDENTITY_EXTERNAL.json')) if os.path.exists(RD + '/IDENTITY_EXTERNAL.json') else None; val = json.load(open(RD + '/VALIDATION.json')) if os.path.exists(RD + '/VALIDATION.json') else None; ch = R.get('charges') or {}
L = []
def P(s=''): L.append(s)
P('# START_HERE -- DGP9_SPECTRAL_HEATBATH_CONTINUATION (repair DGP8 + one substantive frozen continuation; 27 Nov 2026)'); P()
P('Read in this order: this file; REPORT.md (the five gates with every table); THEORY_RETURN.md (which term limits the result; the next lever); PROTOCOL.md (frozen before any code); PROOF_TO_CODE.md (statement -> producer -> independent check -> control); REPAIR_TABLE.md (every review finding: parent failure, repaired success, control / probe); FREEZE.json (commit, identities, the frozen mechanism constants); BUDGET_DECLARATION.json + CHARGES.json + DGP9_FINAL_LEDGER_SIDECAR.json (every charged attempt); ERRATA_DGP8.md (the corrections to the DGP8 records, nothing rewritten).'); P()
P('Frozen pgm `%s` on branch `dgp9-heatbath-continuation` (parent ebf994c = the DGP8 tip; the DGP8 engine ad20e73 is the pinned parent of every before-probe). The accepted default v2.13.2 is unchanged; the branch is pushed and NOT merged.' % (fr['code'].get('commit') or '?')[:12]); P()
P('## The five gates'); P()
P('1. Validity: **%s** -- controls D1-D90 from the clean checkout, the review\'s findings RV1-RV7 absent at the frozen commit (present on the pinned parent), the recovered references, no late row, ledger identity on every heat-bath cell.' % G['validity']['status'])
P('2. Mechanism: **%s** -- weak n64 card-4 clique admission with a checked gap (HB_REVISED, both seeds); the revised checkpoint plan executes past the DGP8 cap on the near-misses.' % G['mechanism']['status'])
P('3. Inference (exposed, observed): **%s**; DGP8 ER gain retained: %s; new completions: %s.' % (G['inference']['status'], G['inference']['er_gain_retained'], G['inference']['new_completions'] or 'NONE'))
P('4. Preservation and cost: **%s**; overhead flags %s; standalone heat-bath losses on passing cases %s.' % (G['preservation_cost']['status'], G['preservation_cost']['overhead']['flags'], G['preservation_cost']['standalone_hb_loses_on_passing_cases']))
P('5. Generalization (fresh, separately): **%s**.' % G['generalization']['status']); P()
P('Limiting terms over the heat-bath cells: %s.' % R['verdict_inputs'].get('limiting_term_counts')); P()
P('## Files'); P()
P('- PACKET/: the brief, the review, the evidence zip (sha256 in PACKET/SHA256.txt; the unpacked tree is reproducible with its bootstrap_review.py), NORMATIVE_INVENTORY.json (every normative file actually used, with hashes).'); P('- controls/before/ (the review\'s probes + the recovered DGP7 probes + the references on the pinned parent), controls/qual/ (D1-D90, suites, PROBES_AFTER at the frozen commit), controls/dev/ (development, charged; UNSUPERVISED_DEV_LOG.md).'); P('- runs/screen, runs/main, runs/fresh, runs/preservation_24 / _18 / _13: every cell (cell.json + result.json + stdout / stderr), one receipt each in DGP9_LEDGER.jsonl.'); P('- MODEL_MANIFEST.json + the per-panel manifests; inputs/ (the EXACT bytes of every manifest input, packet-relative; fresh inputs generated after the freeze); HEATBATH_RATES.json (the frozen rate model).'); P('- harness/: the executed harness files with hashes and the self-contained git bundle; IDENTITY_EXTERNAL.json is written OUTSIDE the results zip (next to it) and attests the final archives.'); P()
P('## Reproduce'); P()
P('`./reproduce.sh restore` (clone the bundle, check out the frozen commit, verify identities) then `controls --only D82,D83`, `cell --id runs/main/<dir>` (the rate model is rewritten to the packet copy and hash-checked), `cohort --manifest MAIN_EXPOSED_MANIFEST.json`, `analyze` (from the restored directory). RESTORE_TEST.sh ran these with the ORIGINAL records directory hidden (reproduce_test/).'); P()
if ident: P('Archives: %s' % json.dumps({k: (v.get('sha256') or '')[:16] for k, v in (ident.get('archives') or {}).items()}))
if val: P('Validation: all_ok %s (%d checks).' % (val.get('all_ok'), len(val.get('checks') or [])))
P('Charges: %s s of %s (%s receipts).' % (ch.get('total_s'), ch.get('ceiling_s'), ch.get('n_receipts'))); P()
P('## Not claimed'); P(); P('Strong frustrated graphs; deployment; an integrated selector or its preservation (SELECT not implemented); any predicted completion; anything from the packet references that did not run.')
open(RD + '/START_HERE.md', 'w').write('\n'.join(L) + '\n'); print('START_HERE.md written')
