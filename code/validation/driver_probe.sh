#!/bin/bash
# Stub-only control of the reproduction driver (no solver runs, no external input).
#   driver_probe.sh REPRODUCE.sh clean            -- every stage succeeds and writes full expected rows: exit 0, token printed
#   driver_probe.sh REPRODUCE.sh fail:<stage>     -- the named required stage exits 19: exit != 0, no token
#   driver_probe.sh REPRODUCE.sh empty_matrix     -- matrices report {"passed":0,"failed":0} with no rows: must fail
#   driver_probe.sh REPRODUCE.sh missing_row      -- acceptance lacks P5: must fail
#   driver_probe.sh REPRODUCE.sh duplicate_row    -- acceptance has P3 twice: must fail
#   driver_probe.sh REPRODUCE.sh blocked_row      -- route matrix R6 is BLOCKED while summary says failed 0: must fail
#   driver_probe.sh REPRODUCE.sh wrong_truth      -- the inline ring diagnostic's solver result misses truth: must fail
#   driver_probe.sh REPRODUCE.sh result_false     -- acceptance P1 is labelled PASS but its own result.ok is false: must fail (r26)
#   driver_probe.sh REPRODUCE.sh result_missing   -- acceptance P1 is labelled PASS but carries no result object: must fail (r26)
# Stages: interpreter inline_1..inline_5 shipped_tests route_matrix gate_matrix strict_mask strict_witnesses gf_grid_regression acceptance_matrix
set -u
DRIVER="$1"; MODE="$2"
STUBDIR=$(mktemp -d); STUB="$STUBDIR/py"
cat > "$STUB" <<PYSTUB
#!/bin/bash
MODE="$MODE"
FAIL="\${MODE#fail:}"; [ "\$FAIL" = "\$MODE" ] && FAIL=""
rows_json() {   # \$1 list key, \$2 name key, \$3.. identities ; honours MODE variants
  key="\$1"; nk="\$2"; shift 2
  out=""; sep=""
  for id in "\$@"; do
    st="PASS"
    [ "\$MODE" = "blocked_row" ] && [ "\$id" = "R6" ] && st="BLOCKED"
    [ "\$MODE" = "missing_row" ] && [ "\$id" = "P5" ] && continue
    res=", \\"result\\": {\\"ok\\": true}"
    [ "\$MODE" = "result_false" ] && [ "\$id" = "P1" ] && res=", \\"result\\": {\\"ok\\": false}"
    [ "\$MODE" = "result_missing" ] && [ "\$id" = "P1" ] && res=""
    out="\$out\$sep{\\"\$nk\\": \\"\$id stub\\", \\"status\\": \\"\$st\\"\$res}"; sep=", "
    [ "\$MODE" = "duplicate_row" ] && [ "\$id" = "P3" ] && out="\$out, {\\"\$nk\\": \\"P3 stub again\\", \\"status\\": \\"PASS\\", \\"result\\": {\\"ok\\": true}}"
  done
  n=\$(echo "\$out" | grep -o '"status"' | wc -l | tr -d ' ')
  if [ "\$MODE" = "empty_matrix" ]; then printf '{"%s": [], "passed": 0, "failed": 0}' "\$key"; else printf '{"%s": [%s], "passed": %s, "failed": 0}' "\$key" "\$out" "\$n"; fi
}
if [ "\${1:-}" = "-m" ]; then
  case "\${2:-}" in
    pytest)                 [ "\$FAIL" = "shipped_tests" ] && exit 19; echo "1 passed in 0.01s"; exit 0 ;;
    mdi.matrix)             [ "\$FAIL" = "route_matrix" ] && exit 19; rows_json controls control R1 R2 R3 R4 R5 R6 R7 > "\${3}"; exit 0 ;;
    mdi.gates)              [ "\$FAIL" = "gate_matrix" ] && exit 19; rows_json controls control A1 B1 B2 B3 B4 > "\${3}"; exit 0 ;;
    mdi.acceptance)         [ "\$FAIL" = "acceptance_matrix" ] && exit 19; rows_json rows row P1 P2 P3 P4 P5 P6 P7 P8 P9 > "\${3}"; exit 0 ;;
    portfolio.strict_mask)  [ "\$FAIL" = "strict_mask" ] && exit 19
                            printf '{"rows": [{"masked_candidates": [{"strict": true, "residual_pairs_equal_mask": true}]}]}' > "\${3}"; exit 0 ;;
    portfolio.independent_strict_witness) [ "\$FAIL" = "strict_witnesses" ] && exit 19; exit 0 ;;
    benchmark.gf_grid_regression)         [ "\$FAIL" = "gf_grid_regression" ] && exit 19; printf '{"ok": true, "case": {"ok": true}}'; exit 0 ;;
  esac
  exit 0
fi
IN="\$(cat 2>/dev/null)"
case "\$IN" in
  *"need Python 3.12"*)              [ "\$FAIL" = "interpreter" ] && exit 19; echo "interpreter OK (stub)"; exit 0 ;;
  *"7/9 soundness"*|*"true P(x0=1)"*) [ "\$FAIL" = "inline_1" ] && exit 19; exit 0 ;;
  *"r20_ring.json\\", \\"w\\""*)         [ "\$FAIL" = "inline_2" ] && exit 19; [ "\$MODE" = "wrong_truth" ] && exit 1; exit 0 ;;
  *"altered.plan.json"*)             [ "\$FAIL" = "inline_4" ] && exit 19; exit 0 ;;
  *"want = [\\"identity\\"]"*)         [ "\$FAIL" = "inline_3" ] && exit 19; exit 0 ;;
  *"radius_truth.json"*)             [ "\$FAIL" = "inline_5" ] && exit 19; exit 0 ;;
  *"strict-mask obligation"*)        exit 0 ;;
  *"GF grid regression obligation"*) exit 0 ;;
esac
exit 0
PYSTUB
chmod +x "$STUB"
X=$(mktemp -d); mkdir -p "$X/code/validation" "$X/runs"; cp "$DRIVER" "$X/REPRODUCE.sh"
cp "$(dirname "$0")/verdict.py" "$X/code/validation/verdict.py"
( cd "$X" && PY="$STUB" bash REPRODUCE.sh > "$X/out.log" 2>&1 ); code=$?
echo "mode=$MODE driver_exit=$code"; grep -E "STATUS:|problems:|verdict problem" "$X/out.log" | head -4
