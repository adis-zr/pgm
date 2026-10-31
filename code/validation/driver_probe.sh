#!/bin/bash
# Stub-only control for the reproduction driver (no solver runs, no external input):
#   fail19 -- the 7/9 witness step exits 19, every other step exits 0 and writes nothing
#   clean  -- every step exits 0 and the matrix steps write a valid zero-failure summary
set -u
DRIVER="$1"; MODE="$2"
STUBDIR=$(mktemp -d); STUB="$STUBDIR/py"
cat > "$STUB" <<PYSTUB
#!/bin/bash
MODE="$MODE"
if [ "\${1:-}" = "-m" ]; then
  case "\${2:-}" in mdi.matrix|mdi.gates|mdi.acceptance)
    [ "\$MODE" = "clean" ] && printf '{"passed": 1, "failed": 0, "stub": true}' > "\${3}" ;;
  esac
  exit 0
fi
IN="\$(cat 2>/dev/null)"
case "\$IN" in *"7/9 soundness"*|*"true P(x0=1)"*) [ "\$MODE" = "fail19" ] && exit 19 ;; esac
exit 0
PYSTUB
chmod +x "$STUB"
X=$(mktemp -d); mkdir -p "$X/code" "$X/runs"; cp "$DRIVER" "$X/REPRODUCE.sh"
( cd "$X" && PY="$STUB" bash REPRODUCE.sh > "$X/out.log" 2>&1 ); code=$?
echo "driver exit=$code"; grep -E "STATUS:|problems:|\[step inline_1 " "$X/out.log" | head -4
