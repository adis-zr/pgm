#!/usr/bin/env bash
# Host build from pinned release archives, entirely in a new external directory.
# Usage: build.sh ARCHIVE_DIRECTORY NEW_OUTPUT_DIRECTORY [PYTHON]
set -euo pipefail
SOURCES="$(cd "${1:?release archive directory}" && pwd)"
OUTPUT="${2:?new output directory}"
PY="${3:-python3}"
SCRIPT="$(cd "$(dirname "$0")" && pwd)"
if [ -e "$OUTPUT" ]; then echo "Refusing existing build directory: $OUTPUT" >&2; exit 2; fi
mkdir -p "$OUTPUT"
cd "$OUTPUT"
OUTPUT="$PWD"
tar -xzf "$SOURCES/libDAI-0.3.2.tar.gz"
tar -xjf "$SOURCES/boost_1_83_0.tar.bz2" boost_1_83_0/boost
cp libDAI-0.3.2/Makefile.LINUX libDAI-0.3.2/Makefile.conf
make -C libDAI-0.3.2 -B -j2 lib DEBUG= CCINC='-Iinclude -I../boost_1_83_0' CCFLAGS='-O3 -std=c++11 -Wno-deprecated -Wall -W -Wextra -fpic' >libdai-build.log 2>&1
"${CXX:-g++}" -O3 -std=c++11 -IlibDAI-0.3.2/include -Iboost_1_83_0 "$SCRIPT/libdai_mar.cpp" -LlibDAI-0.3.2/lib -ldai -lgmpxx -lgmp -o libdai_mar >libdai-driver-build.log 2>&1
PGM_LIBDAI="$OUTPUT/libdai_mar" "$PY" "$SCRIPT/qualify.py" "$OUTPUT/qualification"
