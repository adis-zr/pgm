#!/bin/zsh
# charged job wrapper: python -m gbidi.supervise with the experiment ledger; usage: job.sh NAME TIMEOUT_S MEM_GIB -- cmd...
set -u
RD=/Users/adis/Workspace/pgm-records/code/runs/mdi_2026-10-28/BLOCKRES_2026-11-19
NAME=$1; TO=$2; MEM=$3; shift 3; [ "$1" = "--" ] && shift
cd /Users/adis/Workspace/pgm/code
exec .venv/bin/python -m gbidi.supervise --ledger $RD/BLOCKRES_LEDGER.jsonl --scope blockres --job "$NAME" --timeout $TO --mem-gib $MEM -- "$@"
