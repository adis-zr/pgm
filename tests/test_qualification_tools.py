"""Repairs R3 / R4: the qualification tools enforce their claims (negative controls)."""
import copy, importlib.util, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tests/qualification"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, TOOLS / (name + ".py")); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


def _ok_rows(W, fixture):
    keys, cards = W.expected_inventory(fixture); rows = []
    for v, a in sorted(keys):
        rows.append(dict(variable=v, var=v, state=a, lo="1/%d" % cards[v], hi="1/%d" % cards[v], point="1/%d" % cards[v], guarantee="EXACT"))
    return rows


def passing_receipt():
    W = _load("clean_wheel_relocation_test")
    steps = {}
    for name in W.REQUIRED: steps[name] = dict(returncode=0, stdout_tail="")
    steps["module_origins"]["stdout_tail"] = json.dumps(dict(all_from_site_packages=True))
    steps["capabilities"]["stdout_tail"] = json.dumps({k: dict(status="selectable") for k in ("structural", "block", "quotient", "response")} | {"cqr": dict(status="specialist")})
    def res(outcome, fixture, guarantee, **kw):
        rows = _ok_rows(W, fixture)
        base = dict(outcome=outcome, K=len(rows), published=len(rows), guarantee=guarantee, positive_mass_witness=True, answers=rows, attempts=[], mechanism={}); base.update(kw); return base
    steps["cli_accepted"]["result"] = res("COMPLETE", "pos4.uai", "EXACT", policy="accepted", policy_version="accepted-engine-v2.13.2-targeted/1", attempts=[dict(backend="block", outcome="COMPLETE")])
    steps["cli_experimental"]["result"] = res("COMPLETE", "pos4.uai", "DETERMINISTIC", policy="experimental", policy_version="structural-portfolio-1", attempts=[dict(backend="structural", outcome="COMPLETE")])
    steps["worker_structural"]["result"] = res("COMPLETE", "asym2.uai", "DETERMINISTIC", mechanism=dict(route="structural"))
    steps["worker_stream"]["result"] = res("COMPLETE", "bip4.uai", "DETERMINISTIC", mechanism=dict(route="structural", stats=dict(components=[dict(route="stream", stats=dict(solver="certified_binary64_product_tree_stream", native_event_counter_bound=1))])))
    steps["worker_block"]["result"] = res("COMPLETE", "cyc3_card3.uai", "EXACT"); steps["worker_quotient"]["result"] = res("COMPLETE", "cyc3_card3.uai", "DETERMINISTIC")
    steps["worker_response"]["result"] = res("COMPLETE", "pos4.uai", "PAC", mechanism=dict(route="spectral_heatbath_response"))
    for r in steps["worker_response"]["result"]["answers"]: r.update(guarantee="PAC", lo="99/200", hi="101/200", point="1/2")
    steps["specialists"]["result"] = dict(cbi=dict(status="CERTIFIED", verified=True, origin="/x/site-packages/cbi/api.py"), sf=dict(route_status="OK", checker="VERIFIED", origin="/x/site-packages/sf/core.py"), h4a=dict(available=True, witness=dict(all_ok=True, roles=4, verdicts={name: "VERIFIED" for name in ("C", "PI", "PP")}), source_unchanged=True), cqr=dict(kind="VERIFIED", origin="/x/site-packages/pgm/algorithms/cqr/task.py", cases=dict(queries=dict(verified=True, points=["2/5", "1/2", "3/4"]), normalizer=dict(verified=True, points=["10"]))), method_registry={name: dict(module="pgm.specialists." + name, status="reference" if name == "h4" else "specialist") for name in ("cbi", "sf", "cqr", "h4")})
    steps["native_cache_override"]["result"] = dict(under_override=True, identity_ok=True, stream_under_override=True)
    steps["native_build_locations"]["result"] = dict(cex_lib="/x/site-packages/pgm/a", cex_lib_exists=True, stream_lib="/x/site-packages/pgm/b", stream_lib_exists=True, heat_record="/x/site-packages/pgm/c", heat_record_exists=True, outside_package=True, under_declared_cache=True, source_unchanged=True)
    return dict(steps=steps), W


def test_passing_receipt_passes_and_each_mutation_fails():
    receipt, W = passing_receipt()
    assert W.verdict(receipt)[0] == "PASS"
    mutations = {
        "worker exit 1 with a dictionary-shaped refusal": lambda r: (r["steps"]["worker_block"].update(returncode=1), r["steps"]["worker_block"]["result"].update(outcome="REFUSED", published=0)),
        "all four workers refuse": lambda r: [r["steps"][w]["result"].update(outcome="REFUSED", published=0) for w in ("worker_structural", "worker_stream", "worker_block", "worker_quotient", "worker_response")],
        "wrong policy recorded": lambda r: r["steps"]["cli_accepted"]["result"].update(policy="experimental"),
        "wrong policy version": lambda r: r["steps"]["cli_experimental"]["result"].update(policy_version="structural-portfolio-2"),
        "accepted answered by the wrong backend": lambda r: r["steps"]["cli_accepted"]["result"].update(attempts=[dict(backend="structural", outcome="COMPLETE")]),
        "stream not native": lambda r: r["steps"]["worker_stream"]["result"]["mechanism"]["stats"]["components"][0]["stats"].pop("native_event_counter_bound"),
        "stream fell back to another route": lambda r: r["steps"]["worker_stream"]["result"]["mechanism"]["stats"]["components"][0].update(route="support"),
        "missing inventory row": lambda r: r["steps"]["worker_block"]["result"]["answers"].pop(),
        "duplicate state keys (every state set to 0, counts unchanged)": lambda r: [row.update(state=0) for row in r["steps"]["worker_block"]["result"]["answers"]],
        "coordinate from a foreign variable": lambda r: r["steps"]["worker_block"]["result"]["answers"][0].update(variable=99, var=99),
        "box with the wrong number of states": lambda r: [row.update(state=min(row["state"], 1)) for row in r["steps"]["worker_block"]["result"]["answers"]],
        "exact row with width": lambda r: r["steps"]["worker_block"]["result"]["answers"][0].update(hi="3/4"),
        "box outside the simplex": lambda r: [row.update(lo="3/4", hi="3/4", point="3/4") for row in r["steps"]["worker_quotient"]["result"]["answers"][:2]],
        "no positive-mass witness": lambda r: r["steps"]["cli_accepted"]["result"].update(positive_mass_witness=None),
        "capability probe failed": lambda r: r["steps"]["capabilities"].update(returncode=1),
        "module outside site-packages": lambda r: r["steps"]["module_origins"].update(stdout_tail=json.dumps(dict(all_from_site_packages=False))),
        "cache override not honoured": lambda r: r["steps"]["native_cache_override"]["result"].update(under_override=False),
        "cache binary identity mismatch": lambda r: r["steps"]["native_cache_override"]["result"].update(identity_ok=False),
        "stream library never built": lambda r: r["steps"]["native_build_locations"]["result"].update(stream_lib_exists=False),
        "native build modifies installation": lambda r: r["steps"]["native_build_locations"]["result"].update(source_unchanged=False),
        "native build escapes declared cache": lambda r: r["steps"]["native_build_locations"]["result"].update(under_declared_cache=False),
        "CBI not certified": lambda r: r["steps"]["specialists"]["result"]["cbi"].update(status="VALID_BUT_TOO_WIDE"),
        "SF checker failed": lambda r: r["steps"]["specialists"]["result"]["sf"].update(checker="FAILED: x"),
        "cqr missing from wheel": lambda r: r["steps"]["specialists"]["result"]["cqr"].update(kind="UNAVAILABLE"),
        "cqr wrong exact query": lambda r: r["steps"]["specialists"]["result"]["cqr"]["cases"]["queries"].update(points=["1/2", "1/2", "3/4"]),
        "cqr checker not run": lambda r: r["steps"]["specialists"]["result"]["cqr"]["cases"]["normalizer"].update(verified=False),
        "h4 checker not run": lambda r: r["steps"]["specialists"]["result"]["h4a"]["witness"]["verdicts"].update(PP="FAILED"),
        "h4 mutates installed source": lambda r: r["steps"]["specialists"]["result"]["h4a"].update(source_unchanged=False),
        "method omitted": lambda r: r["steps"]["specialists"]["result"]["method_registry"].pop("cqr"),
        "required step missing": lambda r: r["steps"].pop("worker_response"),
    }
    for name, mutate in mutations.items():
        r = copy.deepcopy(receipt); mutate(r)
        v, failures = W.verdict(r)
        assert v == "FAIL" and failures, name


def test_inherited_control_classifier_never_hides_a_failure_behind_a_static_reference():
    C = _load("run_inherited_controls")
    assert C.classify(ok=True, timeout=False, preflight_missing=[], evidence_missing=[]) == "PORTABLE"
    assert C.classify(ok=False, timeout=False, preflight_missing=[], evidence_missing=[]) == "FAILED"            # a RuntimeError with its dependency PRESENT stays FAILED
    assert C.classify(ok=False, timeout=False, preflight_missing=["/records/x.uai"], evidence_missing=[]) == "BLOCKED"
    assert C.classify(ok=False, timeout=False, preflight_missing=[], evidence_missing=["/records/y.json"]) == "BLOCKED"
    assert C.classify(ok=False, timeout=True, preflight_missing=["/records/x.uai"], evidence_missing=[]) == "TIMEOUT"
    # validated evidence: only paths that are actually absent count; an existing path named in the record is not evidence
    present = str(ROOT / "tests/parity/fixtures/asym2.uai")
    assert C.missing_evidence(dict(fixtures=[dict(missing="/records/code/runs/absent.uai")]), "", "", "/records") == ["/records/code/runs/absent.uai"]
    assert C.missing_evidence(dict(fixtures=[dict(missing=present)]), "", "", "/records") == []
    assert C.missing_evidence({}, "", "RuntimeError: injected new regression", "/records") == []


def test_declared_dependency_preflight_reads_the_suite():
    C = _load("run_inherited_controls")
    root = "/nonexistent-records-root"
    constants = C.module_constants(root)
    assert constants["RECORDS"] == root and all(v.startswith(root) for v in constants.values())
    deps = C.declared_dependencies(root, constants)
    assert deps["D1_forced_pac_matches_accepted"] and all(p.startswith(root) for p in deps["D1_forced_pac_matches_accepted"])
    assert deps["D90_recovered_references"] and not deps["D72_interaction_matrix_and_witness_algebra"]
