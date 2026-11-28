#!/bin/sh
# Qualify the current layout into a fresh scratch directory. Archived qualification
# receipts are never overwritten. Usage: qualify.sh PYTHON BUILD_PYTHON [SCRATCH]
set -u
PY="$1"; BPY="$2"
if [ "$#" -ge 3 ]; then
    SCR="$3"
    if [ -e "$SCR" ]; then echo "Scratch directory must be new: $SCR" >&2; exit 2; fi
    mkdir -p "$SCR" || exit 2
else
    SCR="$(mktemp -d /tmp/pgm-qualify-XXXXXX)"
fi
if [ -z "${PARITY_REFERENCE:-}" ] && [ -z "${PGM_BASELINE_ROOT:-}" ]; then
    echo "Set PARITY_REFERENCE to an explicit same-host reference, or PGM_BASELINE_ROOT to its pinned checkout" >&2; exit 2
fi
REPO="$(cd "$(dirname "$0")/../.." && pwd)"; Q="$SCR/qualification"; T="$REPO/tests/qualification"
if [ -e "$Q" ]; then echo "Refusing existing qualification directory: $Q" >&2; exit 2; fi
mkdir -p "$Q" "$SCR"; cd "$REPO" || exit 2
LOG="$Q/COMMANDS.log"; : > "$LOG"
run() { name="$1"; shift; echo "## $name: $*" >> "$LOG"; "$@" > "$Q/$name.log" 2>&1; rc=$?; echo "exit $rc" >> "$LOG"; echo "$name exit $rc"; return "$rc"; }
export PYTHONPATH="$REPO/src:$REPO"
git -C "$REPO" rev-parse HEAD > "$Q/SOURCE_COMMIT.txt"; git -C "$REPO" status --porcelain > "$Q/GIT_STATUS.txt"
# Native compilation is explicit setup, never charged to route-selection controls.
# Full qualification requires the H4 C++/MPFR/GMP development dependencies too.
if ! run 00_native_setup "$PY" -m pgm.runtime.build --h4; then
    echo "Native setup failed; qualification stopped before timed route controls" >&2; exit 1
fi
run 01_pytest "$PY" -m pytest tests -q -rA -p no:cacheprovider
run 02_parity_generate "$PY" tests/parity/generate_reference.py "$SCR/parity_final.json"
if [ -n "${PARITY_REFERENCE:-}" ]; then
    REF="$PARITY_REFERENCE"
else
    REF="$SCR/parity_baseline.json"
    ( cd "$PGM_BASELINE_ROOT" && run 02b_baseline_generate env PYTHONPATH="$PGM_BASELINE_ROOT/src:$PGM_BASELINE_ROOT/code" "$PY" tests/parity/generate_reference.py "$REF" )
fi
run 03_parity_compare "$PY" tests/parity/compare.py "$SCR/parity_final.json" --reference "$REF" --report "$Q/parity_report.json"
cp "$SCR/parity_final.json" "$Q/parity_candidate.json"
run 04_check_dgp10 "$PY" -m research.campaigns.hp.check_dgp10 "$Q/check_dgp10.json"
run 05_dgp10_oracle "$PY" -m research.campaigns.hp.dgp10_oracle "$Q/dgp10_oracle.json"
run 06_inherited_controls "$PY" "$T/run_inherited_controls.py" "$Q/BLOCKED_CONTROLS.json" --timeout 900
run 07_specialist_conformance "$PY" -m pytest tests/specialists tests/benchmark_legacy -q -rA -p no:cacheprovider --continue-on-collection-errors
"$PY" - "$REPO" "$SCR/wheel_source" <<'COPYEOF'
from pathlib import Path
import shutil, sys
source, target = map(Path, sys.argv[1:]); target.mkdir()
shutil.copy2(source / "pyproject.toml", target / "pyproject.toml")
shutil.copytree(source / "src", target / "src", ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.egg-info", "native_cache"))
COPYEOF
run 08_wheel_build "$BPY" -m build --wheel --no-isolation --outdir "$SCR/dist" "$SCR/wheel_source"
WHEEL="$(ls "$SCR"/dist/*.whl 2>/dev/null | head -1)"
if [ -n "$WHEEL" ]; then shasum -a 256 "$WHEEL" > "$Q/WHEEL_SHA256.txt"; unzip -l "$WHEEL" > "$Q/wheel_contents.txt"; run 09_clean_wheel_relocation "$PY" "$T/clean_wheel_relocation_test.py" "$WHEEL" "$SCR/relocation"; cp "$SCR/relocation/clean_wheel_relocation.json" "$Q/" 2>/dev/null; else echo "## 09_clean_wheel_relocation: (no wheel)" >> "$LOG"; echo "exit 1" >> "$LOG"; fi
"$PY" - "$Q" <<'PYEOF'
import json, re, sys, platform
from pathlib import Path
Q = Path(sys.argv[1])
REQUIRED = ["00_native_setup", "01_pytest", "02_parity_generate", "03_parity_compare", "04_check_dgp10", "05_dgp10_oracle", "06_inherited_controls", "07_specialist_conformance", "08_wheel_build", "09_clean_wheel_relocation"]
out = dict(commit=(Q / "SOURCE_COMMIT.txt").read_text().strip(), git_status_dirty_lines=(Q / "GIT_STATUS.txt").read_text().splitlines(), python=sys.version.split()[0], platform=platform.platform())
log = (Q / "COMMANDS.log").read_text(); out["commands"] = [dict(step=m.group(1), command=m.group(2), exit=int(m.group(3))) for m in re.finditer(r"## (\S+): (.*)\nexit (\d+)", log)]
exits = {c["step"]: c["exit"] for c in out["commands"]}
def text(n): p = Q / (n + ".log"); return p.read_text() if p.exists() else ""
def tail(n): t = text(n).strip(); return t.splitlines()[-1] if t else None
def pytest_summary(n):
    t = text(n); last = tail(n) or ""
    skips = [l.strip() for l in t.splitlines() if l.startswith("SKIPPED") and "BLOCKED" in l]
    return dict(summary=last, collection_errors=len(re.findall(r"^ERROR (?:collecting )?[\w/\.]+", t, re.M)), blocked_skips=skips, blocked_test_instances=sum(int(m.group(1)) for l in skips for m in [re.match(r"SKIPPED \[(\d+)\]", l)] if m), failed=[l.strip() for l in t.splitlines() if l.startswith("FAILED")])
out["pytest"] = pytest_summary("01_pytest"); out["specialist_conformance"] = pytest_summary("07_specialist_conformance")
out["parity"] = json.loads((Q / "parity_report.json").read_text())["verdict"] if (Q / "parity_report.json").exists() else None
d10 = json.loads((Q / "check_dgp10.json").read_text()) if (Q / "check_dgp10.json").exists() else {}; out["check_dgp10"] = dict(all_ok=d10.get("all_ok"), n_ok=d10.get("n_ok"), n=d10.get("n"))
orc = json.loads((Q / "dgp10_oracle.json").read_text()) if (Q / "dgp10_oracle.json").exists() else {}; out["dgp10_oracle"] = dict(all_ok=orc.get("all_ok"), gate=orc.get("gate"), models=len(orc.get("models", {})), nonvacuous=len(orc.get("nonvacuous_models", [])))
bc = json.loads((Q / "BLOCKED_CONTROLS.json").read_text()) if (Q / "BLOCKED_CONTROLS.json").exists() else {}; out["inherited_controls"] = dict(counts=bc.get("counts"), classification=bc.get("classification"))
out["wheel"] = (Q / "WHEEL_SHA256.txt").read_text().split()[0] if (Q / "WHEEL_SHA256.txt").exists() else None
rel = json.loads((Q / "clean_wheel_relocation.json").read_text()) if (Q / "clean_wheel_relocation.json").exists() else {}; out["clean_wheel_relocation"] = dict(verdict=rel.get("verdict"), failures=rel.get("failures"))
out["required_steps"] = REQUIRED; out["required_exit_codes"] = {s: exits.get(s) for s in REQUIRED}
failed_required = [s for s in REQUIRED if exits.get(s) != 0]
out["blocked"] = dict(inherited_controls=(bc.get("counts") or {}).get("BLOCKED"), specialist_tests=out["specialist_conformance"]["blocked_test_instances"], specialist_skip_lines=len(out["specialist_conformance"]["blocked_skips"]), note="blocked = declared private-record dependencies absent on this host; specialist_tests counts test INSTANCES (pytest aggregates skip lines); listed per item in BLOCKED_CONTROLS.json and the pytest log")
out["failed"] = dict(required_steps=failed_required, specialist_collection_errors=out["specialist_conformance"]["collection_errors"], specialist_failed=out["specialist_conformance"]["failed"], pytest_failed=out["pytest"]["failed"])
out["overall"] = "PASS" if (not failed_required and out["parity"] == "IDENTICAL" and out["check_dgp10"].get("all_ok") and out["dgp10_oracle"].get("all_ok") and out["clean_wheel_relocation"].get("verdict") == "PASS" and out["specialist_conformance"]["collection_errors"] == 0 and not out["specialist_conformance"]["failed"] and not out["pytest"]["failed"]) else "FAIL"
(Q / "QUALIFICATION.json").write_text(json.dumps(out, indent=1) + "\n"); print(json.dumps({k: v for k, v in out.items() if k not in ("commands",)}, indent=1))
sys.exit(0 if out["overall"] == "PASS" else 1)
PYEOF
rc=$?; echo "combined qualification overall exit $rc"; exit $rc
