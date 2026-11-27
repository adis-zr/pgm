#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Dependencies were downloaded from the official release sites, hashes in LIBDAI_BUILD.json.
tar -xzf libDAI-0.3.2.tar.gz
if [ ! -d boost_1_83_0/boost ]; then tar -xjf boost_1_83_0.tar.bz2 boost_1_83_0/boost; fi
cp libDAI-0.3.2/Makefile.LINUX libDAI-0.3.2/Makefile.conf
make -C libDAI-0.3.2 -B -j2 lib DEBUG= CCINC='-Iinclude -I../boost_1_83_0' CCFLAGS='-O3 -std=c++11 -Wno-deprecated -Wall -W -Wextra -fpic' >libdai-build.log 2>&1
g++ -O3 -std=c++11 -IlibDAI-0.3.2/include -Iboost_1_83_0 ../pgm-external-benchmark/code/bench/libdai/libdai_mar.cpp -LlibDAI-0.3.2/lib -ldai -lgmpxx -lgmp -o libdai_mar >libdai-driver-build.log 2>&1
python qualify_libdai.py
