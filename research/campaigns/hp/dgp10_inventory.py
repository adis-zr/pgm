"""DGP10: (a) `inventory` -- the NORMATIVE INVENTORY (PACKET/NORMATIVE_INVENTORY.json): every supplied normative file actually used (the three delivered files, the packet members: FROZEN_EXPERIMENT_SPEC, repair plan, the reference scripts +
receipts, the DGP9 review + carried contract, every carried probe, the DGP9 rate file, the DGP9 manifests) with sha256 and the role it played; (b) `probes-summary` -- the per-probe finding booleans of a probe layout (before = the pinned
parent, after = the frozen commit) into PROBES_SUMMARY.json (all_present / all_absent), using the probes' own recorded fields. usage: dgp10_inventory.py inventory | probes-summary LAYOUT_DIR OUT.json [--label before|after]"""

# Source-checkout entry point; production imports never traverse research.
if __package__ in (None, ""):
    import sys as _research_sys
    from pathlib import Path as _ResearchPath
    _research_sys.path.insert(0, str(_ResearchPath(__file__).resolve().parents[3]))
from research.bootstrap import activate as _activate_research
_activate_research()
from research.paths import repo_root as _repo_root, runs_root as _runs_root, records_root as _records_root, source_path as _source_path
import os, sys, json, hashlib, time, glob
RD = os.environ.get('DGP10_RD', str(_runs_root() / 'mdi_2026-10-28/DGP10_QUERY_RESPONSE')); PKT = os.path.join(RD, 'PACKET', 'packet', 'DGP10_QUERY_RESPONSE_PACKET_2026-11-26')
def sha(p): return hashlib.sha256(open(p, 'rb').read()).hexdigest()


def inventory():
    files = {}
    def add(key, path, role):
        if os.path.exists(path): files[key] = dict(path=os.path.relpath(path, RD), sha256=sha(path), bytes=os.path.getsize(path), role=role)
        else: files[key] = dict(path=os.path.relpath(path, RD), missing=True, role=role)
    add('brief', os.path.join(RD, 'PACKET', 'CLAUDE_DGP10_QUERY_RESPONSE_AND_REPAIRS.md'), 'the implementation brief (normative order 2)'); add('theory', os.path.join(RD, 'PACKET', 'DGP10_QUERY_RESPONSE_THEORY_2026-11-26.md'), 'the theory note (normative order 1)'); add('external_identity', os.path.join(RD, 'PACKET', 'DGP10_PACKET_EXTERNAL_IDENTITY.json'), 'the packet external identity manifest (names the zip)')
    add('spec', os.path.join(PKT, 'dgp10_theory', 'FROZEN_EXPERIMENT_SPEC.md'), 'the frozen experiment (normative order 3)'); add('carried_contract', os.path.join(PKT, 'DGP9_CARRIED_REPAIR_CONTRACT.md'), 'the carried repair contract (normative order 4)'); add('dgp9_review', os.path.join(PKT, 'DGP9_INDEPENDENT_REVIEW_2026-11-26.md'), 'the DGP9 independent review (findings F9-1..F9-5)')
    add('repair_plan', os.path.join(PKT, 'dgp10_theory', 'repair_plan.md'), 'repair design (explanatory)'); add('practical_note', os.path.join(PKT, 'dgp10_practical', 'PRACTICAL_ALGORITHM_NOTE.md'), 'the observer arithmetic recipe (explanatory; obligations checked independently in D92 / the oracle)'); add('theory_review_status', os.path.join(PKT, 'dgp10_theory', 'THEORY_REVIEW_STATUS.md'), 'theory-turn review record')
    add('reference_checked_tilt', os.path.join(PKT, 'dgp10_theory', 'reference_checked_tilt.py'), 'the exact scalar checker reference: byte-identical production copy cex/hp/checked_tilt.py'); add('reference_exact_response', os.path.join(PKT, 'dgp10_theory', 'reference_exact_response.py'), 'exact response identities reference (run by bootstrap references)')
    for f in ('trace_gap_reference.py', 'scalar_resolvent_reference.py', 'hermite_resolvent_reference.py', 'ADVERSARIAL_NOTE.md'): add('adversarial/' + f, os.path.join(PKT, 'dgp10_theory', 'adversarial', f), 'independent numerical diagnostic (run by bootstrap references)')
    add('bootstrap', os.path.join(PKT, 'bootstrap.py'), 'fail-closed packet bootstrap (verify / restore-parent / references)'); add('packet_manifest', os.path.join(PKT, 'PACKET_MANIFEST.json'), 'per-member hashes of the packet')
    for p in sorted(glob.glob(os.path.join(PKT, 'dgp9_review', '*', '*.py'))): add('probe/' + os.path.relpath(p, os.path.join(PKT, 'dgp9_review')), p, 'carried DGP9 review probe (before: pinned parent; after: frozen commit)')
    add('uniform_scaled_triangle', os.path.join(PKT, 'dgp9_review', 'native_audit', 'uniform_scaled_triangle.uai'), 'probe fixture')
    R9 = os.path.join(PKT, 'dgp9_review', 'records', 'DGP9_SPECTRAL_HEATBATH_CONTINUATION')
    for f in ('HEATBATH_RATES.json', 'MAIN_EXPOSED_MANIFEST.json', 'FRESH_MANIFEST.json', 'PRESERVATION_24_MANIFEST.json', 'PRESERVATION_18_MANIFEST.json', 'PRESERVATION_13_MANIFEST.json', 'PROTOCOL.md', 'RESULTS.json'): add('dgp9/' + f, os.path.join(R9, f), 'the restored DGP9 records (rate file = HB_R\'s exact bytes; manifests = the exposed / preservation inputs; PROTOCOL = the seed rule; RESULTS = archived radii)')
    add('dgp9_bundle', os.path.join(R9, 'harness', 'pgm-dgp9-heatbath-continuation.bundle'), 'the DGP9 git bundle (restore-parent clones d1932cf from it)')
    out = dict(experiment='DGP10_QUERY_RESPONSE', utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), packet_zip=dict(path='~/Downloads/DGP10_QUERY_RESPONSE_PACKET_2026-11-26.zip', sha256='984043e3e15ddd67ec8b222ce1342ff4bdc01309adb4d3ecb13ae1a23d79a291', bytes=68480040, verified_by='bootstrap verify (controls/bootstrap/verify_receipt.json; 120 members)'), files=files, n=len(files), missing=[k for k, v in files.items() if v.get('missing')],
               normative_order='theory note; brief; FROZEN_EXPERIMENT_SPEC; DGP9_CARRIED_REPAIR_CONTRACT; executable reference semantics (theory section 9)', note='the unpacked packet (PACKET/packet) is reproducible from the zip; its members are hashed here; the normative inventory is bound into FREEZE.json by sha256')
    json.dump(out, open(os.path.join(RD, 'PACKET', 'NORMATIVE_INVENTORY.json'), 'w'), indent=1); print(json.dumps(dict(n=out['n'], missing=out['missing'])))


def probes_summary(layout, out_path, label):
    """the finding booleans per probe from the probes' own JSON: a finding is PRESENT when the probe's recorded field says so"""
    L = os.path.join(layout, 'dgp9_review'); S = {}
    def ld(p):
        try: return json.load(open(os.path.join(L, p)))
        except Exception: return None
    d = ld('spectral_audit/probe_resource_failures.json') or {}
    S['spectral_partial_reservations'] = dict(present=bool((d.get('second_reservation_refusal') or {}).get('live_after', 0) > 0 or (d.get('cache_on_deadline') or {}).get('live_after', 0) > 0 or (d.get('retained_charge_on_deadline') or {}).get('live_after', 0) > 0), live_after=[(d.get(k) or {}).get('live_after') for k in ('second_reservation_refusal', 'cache_on_deadline', 'retained_charge_on_deadline')])
    S['spectral_retained_aliases_after_release'] = dict(present=bool((d.get('retained_release') or {}).get('h_still_reachable')))
    S['spectral_identity_allocated_before_admission'] = dict(present=bool(((d.get('proof_zero_headroom') or {}).get('peak_traced_bytes') or 0) > 65536), peak=(d.get('proof_zero_headroom') or {}).get('peak_traced_bytes'))
    d = ld('native_audit/probe_native_boundaries.json') or {}
    S['native_staging_orphan'] = dict(present=bool((d.get('staging_refusal') or {}).get('live_after_refusal', 0) > 0), live_after=(d.get('staging_refusal') or {}).get('live_after_refusal'))
    S['native_fallback_weights_before_admission'] = dict(present=bool(((d.get('fallback_pre_admission') or {}).get('peak_traced_bytes') or 0) > 16384), peak=(d.get('fallback_pre_admission') or {}).get('peak_traced_bytes'))
    g = d.get('range_witness_growth') or {}; S['native_range_witness_growth'] = dict(present=bool(g and g.get('peak_traced_bytes', 0) > 2 * max(1, g.get('estimated_charge', 1))), peak=g.get('peak_traced_bytes'), estimate=g.get('estimated_charge'), seconds=g.get('seconds'))
    S['native_compile_timeout_floor'] = dict(present=bool(((d.get('build_timeout') or {}).get('compiler_timeout') or 0) > ((d.get('build_timeout') or {}).get('remaining_allowance') or 0) + 1e-9), compiler_timeout=(d.get('build_timeout') or {}).get('compiler_timeout'))
    d = ld('native_audit/probe_native_deadline.json') or {}; S['native_unpolled_preparation'] = dict(present=bool((d.get('elapsed_s') or 0) > 0.1), elapsed_s=d.get('elapsed_s'), returned=d.get('returned'))
    d = ld('repair_audit/probe_partial_plan_ownership.json') or {}; S['two_plan_orphan'] = dict(present=bool(d.get('finding_present')), live_after=d.get('live_after_refusal_and_gc'))
    d = ld('repair_audit/probe_commit_boundaries.json') or {}; r = d.get('residual_postcommit_diagnostic_crossing') or {}; S['residual_postcommit_variable_tail'] = dict(present=bool(r.get('variable_diagnostic_tail_remains')), result=r.get('result'), status_why=r.get('status_why'))
    S['batch_epoch_crossings_fixed_in_dgp9'] = dict(present=not (((d.get('batch_crossing_in_diagnostic_reductions') or {}).get('fixed')) and ((d.get('epoch_crossing_before_single_sample') or {}).get('fixed'))))
    d = ld('markov_audit/probe_publication.json') or {}; S['serialization_after_final_sample'] = dict(present=bool((d.get('new_serialization_crossing') or {}).get('file_outcome') == 'COMPLETE'), file_outcome=(d.get('new_serialization_crossing') or {}).get('file_outcome'))
    S['dgp9_publication_repairs_regressed'] = dict(present=not (bool((d.get('old_missing_scalar') or {}).get('contains')) and (d.get('old_diagnostic_crossing') or {}).get('file_outcome') == 'DEADLINE' and (d.get('old_early_inventory') or {}).get('K') == (d.get('old_early_inventory') or {}).get('answer_count')))
    # numerical regressions (must stay ABSENT on both)
    for key, f, field in (('native_actual_fallback_regressed', 'native_audit/probe_actual_fallback.json', 'all_ok'), ('native_false_publication', 'native_audit/probe_native_false_publication.json', None), ('spectral_false_admission', 'spectral_audit/probe_false_admission.json', None), ('markov_certificates_recheck', 'markov_audit/recheck_certificates.json', 'all_checked_ok'), ('archived_native_range', 'native_audit/check_archived_native_range.json', None)):
        d = ld(f) or {}
        if key == 'native_false_publication': S[key] = dict(present=bool((d.get('wrong_published_rows') or 0) > 0 or d.get('outcome') != 'COMPLETE'), wrong=d.get('wrong_published_rows'), outcome=d.get('outcome'))
        elif key == 'spectral_false_admission': S[key] = dict(present=bool(d.get('returned_eligible')), refusal=(d.get('refusal') or {}).get('kind'))
        elif key == 'archived_native_range': S[key] = dict(present=bool(d and any((m.get('conversion_relative_bound_violations') or 0) > 0 for m in (d.get('models') or []))), models=len(d.get('models') or []))
        else: S[key] = dict(present=(not bool(d.get(field))) if d else None)
    carried = ['spectral_partial_reservations', 'spectral_retained_aliases_after_release', 'spectral_identity_allocated_before_admission', 'native_staging_orphan', 'native_fallback_weights_before_admission', 'native_range_witness_growth', 'native_compile_timeout_floor', 'native_unpolled_preparation', 'two_plan_orphan', 'residual_postcommit_variable_tail', 'serialization_after_final_sample']
    regress = [k for k in S if k not in carried]
    out = dict(label=label, layout=os.path.abspath(layout), utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), findings=S, carried_findings=carried, present={k: S[k]['present'] for k in carried}, n_present=sum(1 for k in carried if S[k]['present']), n_carried=len(carried), all_present=all(S[k]['present'] for k in carried), all_absent=all(S[k]['present'] is False for k in carried), regressions_present=[k for k in regress if S[k].get('present')], regressions_all_absent=all(S[k].get('present') is False for k in regress))
    json.dump(out, open(out_path, 'w'), indent=1); print(json.dumps(dict(label=label, present=out['present'], all_present=out['all_present'], all_absent=out['all_absent'], regressions=out['regressions_present'])))


if __name__ == '__main__':
    if sys.argv[1] == 'inventory': inventory()
    else: probes_summary(sys.argv[2], sys.argv[3], (sys.argv[sys.argv.index('--label') + 1] if '--label' in sys.argv else 'unlabelled'))
