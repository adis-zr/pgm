#!/bin/sh
# ONE combined qualification of consolidation step 1 at the final source state (brief section 8).  Every command is
# recorded with its exit code; receipts land in documentation/consolidation/step1/qualification/06_final/.
# usage: qualify_step1.sh <venv python> <build-venv python> [scratch dir]
set -u
PY="$1"; BPY="$2"; SCR="${3:-$(mktemp -d /tmp/pgm-qualify-XXXXXX)}"
REPO="$(cd "$(dirname "$0")/../../../.." && pwd)"; Q="$REPO/documentation/consolidation/step1/qualification/06_final"; T="$REPO/documentation/consolidation/step1/tools"
mkdir -p "$Q" "$SCR"; cd "$REPO" || exit 2
LOG="$Q/COMMANDS.log"; : > "$LOG"
run() { name="$1"; shift; echo "## $name: $*" >> "$LOG"; "$@" > "$Q/$name.log" 2>&1; rc=$?; echo "exit $rc" >> "$LOG"; echo "$name exit $rc"; }
export PYTHONPATH="$REPO/src:$REPO/code"
git -C "$REPO" rev-parse HEAD > "$Q/SOURCE_COMMIT.txt"; git -C "$REPO" status --porcelain > "$Q/GIT_STATUS.txt"
run 01_pytest "$PY" -m pytest tests -q -rA -p no:cacheprovider
run 02_parity_generate "$PY" tests/parity/generate_reference.py "$SCR/parity_final.json"
run 03_parity_compare "$PY" tests/parity/compare.py "$SCR/parity_final.json" --report "$Q/parity_report.json"
cp "$SCR/parity_final.json" "$Q/parity_candidate.json"
( cd code/cex/hp && run 04_check_dgp10 "$PY" check_dgp10.py "$Q/check_dgp10.json" )
( cd code/cex/hp && run 05_dgp10_oracle "$PY" dgp10_oracle.py "$Q/dgp10_oracle.json" )
run 06_inherited_controls "$PY" "$T/run_inherited_controls.py" "$Q/BLOCKED_CONTROLS.json" --timeout 900
run 07_specialist_conformance "$PY" -m pytest code/tests -q -rA -p no:cacheprovider --continue-on-collection-errors
rm -rf "$SCR/dist" "$REPO/build" "$REPO/pgm_certified.egg-info"
run 08_wheel_build "$BPY" -m build --wheel --no-isolation --outdir "$SCR/dist" .
rm -rf "$REPO/build" "$REPO/pgm_certified.egg-info"
WHEEL="$(ls "$SCR"/dist/*.whl | head -1)"; shasum -a 256 "$WHEEL" > "$Q/WHEEL_SHA256.txt"; cp "$WHEEL" "$SCR/"
unzip -l "$WHEEL" > "$Q/wheel_contents.txt"
run 09_clean_wheel_relocation "$PY" "$T/clean_wheel_relocation_test.py" "$WHEEL" "$SCR/relocation"
cp "$SCR/relocation/clean_wheel_relocation.json" "$Q/"
run 10_closure_manifest "$PY" "$T/manifest.py"
run 11_classification "$PY" "$T/classify_tree.py"
"$PY" - "$Q" <<'PYEOF'
import json, re, sys, subprocess, platform
from pathlib import Path
Q = Path(sys.argv[1]); out = dict(commit=(Q / "SOURCE_COMMIT.txt").read_text().strip(), git_status_dirty_lines=(Q / "GIT_STATUS.txt").read_text().splitlines(), python=sys.version.split()[0], platform=platform.platform())
log = (Q / "COMMANDS.log").read_text(); out["commands"] = [dict(step=m.group(1), command=m.group(2), exit=int(m.group(3))) for m in re.finditer(r"## (\S+): (.*)\nexit (\d+)", log)]
def tail(n): p = Q / (n + ".log"); return p.read_text().strip().splitlines()[-1] if p.exists() and p.read_text().strip() else None
out["pytest_summary"] = tail("01_pytest"); out["parity"] = json.loads((Q / "parity_report.json").read_text())["verdict"] if (Q / "parity_report.json").exists() else None
d10 = json.loads((Q / "check_dgp10.json").read_text()) if (Q / "check_dgp10.json").exists() else {}; out["check_dgp10"] = dict(all_ok=d10.get("all_ok"), n_ok=d10.get("n_ok"), n=d10.get("n"))
orc = json.loads((Q / "dgp10_oracle.json").read_text()) if (Q / "dgp10_oracle.json").exists() else {}; out["dgp10_oracle"] = dict(all_ok=orc.get("all_ok"), gate=orc.get("gate"), models=len(orc.get("models", {})), nonvacuous=len(orc.get("nonvacuous_models", [])))
bc = json.loads((Q / "BLOCKED_CONTROLS.json").read_text()) if (Q / "BLOCKED_CONTROLS.json").exists() else {}; out["inherited_controls"] = bc.get("counts")
out["specialist_conformance"] = tail("07_specialist_conformance"); out["wheel"] = (Q / "WHEEL_SHA256.txt").read_text().split()[0] if (Q / "WHEEL_SHA256.txt").exists() else None
rel = json.loads((Q / "clean_wheel_relocation.json").read_text()) if (Q / "clean_wheel_relocation.json").exists() else {}; out["clean_wheel_relocation"] = rel.get("verdict")
out["all_commands_exit_zero"] = all(c["exit"] == 0 for c in out["commands"] if c["step"] not in ("06_inherited_controls", "07_specialist_conformance"))
(Q / "QUALIFICATION.json").write_text(json.dumps(out, indent=1) + "\n"); print(json.dumps({k: v for k, v in out.items() if k != "commands"}, indent=1))
PYEOF
