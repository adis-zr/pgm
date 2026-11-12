"""Build the AUTHORITATIVE specification of a campaign from records written BEFORE / INDEPENDENTLY of its outputs (follow-up review §4): the supervisor's START
row of the campaign job (command line: --seconds, --route, --cases; recorded before the first case ran), the inputs directory (the expected breadth case set when
no --cases list was declared), and the frozen artifact hash file of the arm (CANDIDATE_FREEZE_SOURCE_HASHES_*.json). The gate (compare_campaigns.py v3) consumes
these specifications and refuses missing / extra / duplicate receipts and any source hash that differs from the frozen artifact.
    python cex/campaign_spec.py <RD> <campaign_job_name> <arm: baseline|newarm> <freeze_json> <inputs_dir> <out_spec.json>"""
import sys, os, json, glob, re
RD, JOB, ARM, FREEZE, INPUTS, OUT = sys.argv[1:7]
starts = [json.loads(l) for l in open(os.path.join(RD, 'CEX_LEDGER.jsonl')) if l.strip()]
starts = [r for r in starts if r.get('kind') == 'START' and r.get('job') == JOB]
if len(starts) != 1: raise SystemExit('expected exactly one START row for %s, found %d' % (JOB, len(starts)))
st = starts[0]; cmd = st['cmd'] if isinstance(st['cmd'], str) else ' '.join(st['cmd'])
def opt(name, default=None):
    m = re.search(r'--%s[ =](\S+)' % name, cmd); return m.group(1) if m else default
seconds = float(opt('seconds')); route = opt('route', 'auto'); cases_decl = opt('cases'); output = opt('output')
inputs_cases = sorted(os.path.basename(p)[:-4] for p in glob.glob(os.path.join(INPUTS, '*.uai')))
cases = sorted(cases_decl.split(',')) if cases_decl else inputs_cases
if any(c not in inputs_cases for c in cases): raise SystemExit('declared case not among the inputs: %s' % [c for c in cases if c not in inputs_cases])
fr = json.load(open(FREEZE)); arm_key = 'baseline' if ARM == 'baseline' else 'newarm'
spec = dict(job=JOB, arm=ARM, start_utc=st['start_utc'], jid=st['jid'], declared_command=cmd, seconds=seconds, route=route, kind='declared panel' if cases_decl else 'breadth (every input case)', expected_cases=cases, inputs_dir=os.path.abspath(INPUTS), output_dir=output,
            frozen_source_hashes=fr[arm_key], frozen_binary_sha256=(fr.get('kernel_build') or {}).get('binary_sha256') if ARM != 'baseline' else None, freeze_file=os.path.abspath(FREEZE), note='expected cases / budget / route come from the supervisor START row recorded before the first case ran; source identities from the frozen artifact file; the gate accepts nothing else')
json.dump(spec, open(OUT, 'w'), indent=1); print(json.dumps({k: spec[k] for k in ('job', 'arm', 'seconds', 'route', 'kind')}, default=str), len(cases), 'cases')
