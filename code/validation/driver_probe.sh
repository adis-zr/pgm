#!/bin/bash
# Stub-only control of the reproduction driver (no solver runs, no external input):
#   driver_probe.sh REPRODUCE.sh clean          -- every stage succeeds and writes a valid zero-failure summary: exit 0, token printed
#   driver_probe.sh REPRODUCE.sh fail:<stage>   -- the named stage fails (exit 19) while every other stage succeeds: exit != 0, no token
# Stages: interpreter inline_1..inline_5 shipped_tests route_matrix gate_matrix strict_mask strict_witnesses gf_grid_regression acceptance_matrix
set -u
DRIVER="$1"; MODE="$2"
STUBDIR=$(mktemp -d); STUB="$STUBDIR/py"
cat > "$STUB" <<PYSTUB
#!/bin/bash
MODE="$MODE"
FAIL="\${MODE#fail:}"; [ "\$FAIL" = "\$MODE" ] && FAIL=""
emit_ok_summary() { printf '{"passed": 1, "failed": 0, "stub": true}' > "\$1"; }
if [ "\${1:-}" = "-m" ]; then
  case "\${2:-}" in
    pytest)                 [ "\$FAIL" = "shipped_tests" ] && exit 19; echo "1 passed in 0.01s"; exit 0 ;;
    mdi.matrix)             [ "\$FAIL" = "route_matrix" ] && exit 19; emit_ok_summary "\${3}"; exit 0 ;;
    mdi.gates)              [ "\$FAIL" = "gate_matrix" ] && exit 19; emit_ok_summary "\${3}"; exit 0 ;;
    mdi.acceptance)         [ "\$FAIL" = "acceptance_matrix" ] && exit 19; emit_ok_summary "\${3}"; exit 0 ;;
    portfolio.strict_mask)  [ "\$FAIL" = "strict_mask" ] && exit 19
                            printf '{"rows": [{"masked_candidates": [{"strict": true, "residual_pairs_equal_mask": true}]}]}' > "\${3}"; exit 0 ;;
    portfolio.independent_strict_witness) [ "\$FAIL" = "strict_witnesses" ] && exit 19; exit 0 ;;
    benchmark.gf_grid_regression)         [ "\$FAIL" = "gf_grid_regression" ] && exit 19; printf '{"ok": true, "case": {"ok": true}}'; exit 0 ;;
  esac
  exit 0
fi
# inline scripts arrive on stdin (the obligation checkers inside the driver too)
IN="\$(cat 2>/dev/null)"
case "\$IN" in
  *"need Python 3.12"*)              [ "\$FAIL" = "interpreter" ] && exit 19; echo "interpreter OK (stub)"; exit 0 ;;
  *"7/9 soundness"*|*"true P(x0=1)"*) [ "\$FAIL" = "inline_1" ] && exit 19; exit 0 ;;
  *"r20_ring.json\", \"w\""*)         [ "\$FAIL" = "inline_2" ] && exit 19; exit 0 ;;
  *"altered.plan.json"*)             [ "\$FAIL" = "inline_4" ] && exit 19; exit 0 ;;
  *"want = [\"identity\"]"*)         [ "\$FAIL" = "inline_3" ] && exit 19; exit 0 ;;
  *"radius_truth.json"*)             [ "\$FAIL" = "inline_5" ] && exit 19; exit 0 ;;
  *"strict-mask obligation"*)        exit 0 ;;
  *"GF grid regression obligation"*) exit 0 ;;
esac
exit 0
PYSTUB
chmod +x "$STUB"
X=$(mktemp -d); mkdir -p "$X/code" "$X/runs"; cp "$DRIVER" "$X/REPRODUCE.sh"
( cd "$X" && PY="$STUB" bash REPRODUCE.sh > "$X/out.log" 2>&1 ); code=$?
echo "mode=$MODE driver_exit=$code"; grep -E "STATUS:|problems:" "$X/out.log" | head -2
