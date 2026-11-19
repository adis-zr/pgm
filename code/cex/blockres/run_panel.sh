#!/bin/zsh
# usage: run_panel.sh OUTSUBDIR BUDGET ARMS(comma: block,factorwise) TASK...   (tasks are names under the certified-executor inputs dir, or absolute .uai paths)
set -u
RD=/Users/adis/Workspace/pgm-records/code/runs/mdi_2026-10-28/BLOCKRES_2026-11-19
IN=/Users/adis/Workspace/pgm/docs/handoff-received-2026-11-11-certified-executor/packet/inputs
SUB=$1; BUDGET=$2; ARMS=$3; shift 3
cd /Users/adis/Workspace/pgm/code
for t in "$@"; do
  case $t in /*) MP=$t; NAME=$(basename ${t%.uai});; *) MP=$IN/$t.uai; NAME=$t;; esac
  for arm in ${(s:,:)ARMS}; do
    OUT=$RD/$SUB/${NAME}__${arm}
    mkdir -p $OUT
    TO=$(python3 -c "print($BUDGET + 1.0)")
    cex/blockres/job.sh "blockres:$SUB:$NAME:$arm" $TO 3 -- .venv/bin/python cex/blockres/blockres.py --input $MP --output $OUT/result.json --budget $BUDGET --bounds $arm --seed 1 > $OUT/stdout.txt 2> $OUT/stderr.txt
    tail -1 $OUT/stderr.txt | cut -c1-200; head -c 900 $OUT/stdout.txt; echo
  done
done
