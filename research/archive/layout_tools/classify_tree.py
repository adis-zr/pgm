"""Classify every tracked file of the repository (brief section 3): production | production-shim | specialist |
correctness-qualification | benchmark-tooling | research-campaign-tooling | historical-evidence | documentation | packaging.
Writes research/CLASSIFICATION.json (machine-readable) and prints the counts.  Rules are explicit path patterns; the
PATH_MAP shims are read from documentation/consolidation/step1/PATH_MAP.json."""
import json, re, subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
PATH_MAP = json.loads((REPO / "documentation/consolidation/step1/PATH_MAP.json").read_text())
SHIMS = set(PATH_MAP["shims"])
RULES = [  # (regex, class, note) -- first match wins
    (r"^src/pgm/algorithms/.*\.(py|c|cpp|json|dylib|so)$", "production", "canonical implementation closure (host binaries excluded from the wheel)"),
    (r"^src/pgm/specialists/", "specialist", "explicit specialist entrypoints"),
    (r"^src/pgm/", "production", "public API, contracts, policies, model boundary, planning, runtime, validation, backends"),
    (r"^tests/parity/", "correctness-qualification", "pinned characterization reference + generator / comparator"),
    (r"^tests/", "correctness-qualification", "portable public / repair / regression tests"),
    (r"^code/tests/", "correctness-qualification", "specialist and adapter conformance tests (run from the checkout)"),
    (r"^benchmarks/external/inputs/", "benchmark-inputs", "frozen external inputs (61 tasks)"),
    (r"^benchmarks/", "benchmark-tooling", "external benchmark harness, protocol, provenance, references"),
    (r"^code/cex/(pac|baseline|b0_frozen_v14|newarm_dev)/", "historical-evidence", "frozen snapshots (pinned references; never imported by production)"),
    (r"^code/ext/", "benchmark-tooling", "external comparator adapters"),
    (r"^code/bench/controls/", "correctness-qualification", "control inputs"),
    (r"^code/bench/", "benchmark-tooling", "benchmark adapters / cells / libDAI driver source"),
    (r"^code/cbi/(experiment|run_case|replay|score|score3|transfer|generators)\.py$", "research-campaign-tooling", "CBI campaign scripts"),
    (r"^code/cbi/", "specialist", "CBI implementation + checker"),
    (r"^code/sf/(generate|runner|report|score|invoke)\.py$", "research-campaign-tooling", "SF campaign scripts"),
    (r"^code/sf/", "specialist", "SF implementation + checker"),
    (r"^code/h4a/(run|report|stagea|stagea_main|crosscheck|refenum)\.py$", "research-campaign-tooling", "H4 campaign driver / reports"),
    (r"^code/h4a/", "specialist", "H4 arithmetic + provenance"),
    (r"^code/native/", "specialist", "H4 native kernel sources (host-built)"),
    (r"^code/build/", "historical-evidence", "host-built H4 executables (pinned; not wheel contents)"),
    (r"^code/cex/cqr/(campaign|closeout|gate|report|acquire|resolve_design|finalize)\.(py|sh)$", "research-campaign-tooling", "CQR campaign"),
    (r"^code/cex/cqr/(qualification|test_\w+)\.py$", "correctness-qualification", "CQR qualification / tests"),
    (r"^code/cex/cqr/CQR_QUALIFICATION\.json$", "historical-evidence", "CQR qualification record"),
    (r"^code/cex/cqr/", "specialist", "CQR implementation (checkout-only)"),
    (r"^code/cex/newarm/(qualification|cex_qualification|native_qualification|reduction_qualification|qualify_dag_additive|review_additive|review_regression|geometry_controls|test_\w+|audit_\w+|smoke_cex|analyze|evaluate)\.py$", "correctness-qualification", "structural qualification / audits"),
    (r"^code/cex/newarm/cex_control_driver\.cpp$", "correctness-qualification", "native control driver"),
    (r"^code/cex/newarm/.*\.json$", "historical-evidence", "structural qualification records"),
    (r"^code/cex/blockres/check_\w+\.py$", "correctness-qualification", "BlockRes round controls"),
    (r"^code/cex/blockres/(run_\w+|r23_gen|transfer_gen|report)\.py$|^code/cex/blockres/job\.sh$", "research-campaign-tooling", "BlockRes campaign"),
    (r"^code/cex/hp/(check_dgp|check_dgp10|check_hp|check_revision|check_unified)\.py$", "correctness-qualification", "DGP / HP control suites (patch-sensitive; import canonical modules through the shims)"),
    (r"^code/cex/hp/(run_\w+|dgp\w*|calibrate_\w+|gen_unified|hp_gen|dense_gen|validate_round)\.py$", "research-campaign-tooling", "DGP campaign runners / analyzers / packagers"),
    (r"^code/cex/hp/fixtures_closeout/", "correctness-qualification", "closeout fixture"),
    (r"^code/cex/(gate_controls|locked_plan)\.py$", "research-campaign-tooling", "campaign-level controls / plan"),
    (r"^code/(gbidi/__init__\.py|cex/\.gitignore|\.gitignore|\.gitkeep|cex/hp/\.gitignore)$", "packaging", "package markers"),
    (r"^code/PINNED_BINARIES\.json$", "historical-evidence", "pinned binary identities"),
    (r"\.md$", "documentation", "notes / reports"),
    (r"^documentation/consolidation/step1/qualification/", "correctness-qualification", "step-1 qualification receipts"),
    (r"^documentation/consolidation/step1/tools/", "packaging", "step-1 consolidation tools"),
    (r"^documentation/", "documentation", "architecture / reviews / consolidation records"),
    (r"^(pyproject\.toml|\.gitignore|\.gitattributes|README\.md)$", "packaging", "repository root"),
]


def classify(path):
    if path in SHIMS: return "production-shim", "alias shim -> " + PATH_MAP["shims"][path]
    for rx, cls, note in RULES:
        if re.search(rx, path): return cls, note
    return "unclassified", ""


def main():
    files = subprocess.run(["git", "-C", str(REPO), "ls-files"], capture_output=True, text=True).stdout.split()
    out = {}; counts = {}
    for f in files:
        cls, note = classify(f); out[f] = dict(cls=cls, note=note); counts[cls] = counts.get(cls, 0) + 1
    (REPO / "research").mkdir(exist_ok=True)
    (REPO / "research/CLASSIFICATION.json").write_text(json.dumps(dict(generated_by="documentation/consolidation/step1/tools/classify_tree.py", counts=dict(sorted(counts.items())), files=out), indent=1) + "\n")
    print(json.dumps(dict(sorted(counts.items())), indent=1))
    un = [f for f, v in out.items() if v["cls"] == "unclassified"]
    if un: print("UNCLASSIFIED:", un[:40])


if __name__ == "__main__": main()
