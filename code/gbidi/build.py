"""Build the GENERAL_BIDI_V1 native executor (links Homebrew MPFR/GMP) with a recorded compiler contract: binary64 nearest-even for the optional
route, MPFR outward for the general route; no fast-math, no contraction, no reassociation. Records compiler executable hash, library hashes,
flags, source and binary hashes.    python -m gbidi.build"""
from __future__ import annotations
import os, sys, json, subprocess, hashlib, platform, time, shutil
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(HERE, "gbidi", "kernel.cpp"); EXT = "dylib" if sys.platform == "darwin" else "so"; LIB = os.path.join(HERE, "gbidi", "libgbidi_kernel." + EXT)
CXX = os.environ.get("GBIDI_CXX", "clang++"); PREFIX = os.environ.get("GBIDI_MPFR_PREFIX", "/opt/homebrew")
FLAGS = ["-std=c++17", "-O2", "-ffp-model=strict", "-ffp-contract=off", "-fno-fast-math", "-fno-unsafe-math-optimizations", "-fno-reciprocal-math", "-fno-associative-math", "-fPIC", "-shared", "-Wall", "-Wextra", "-I" + PREFIX + "/include", "-L" + PREFIX + "/lib", "-lmpfr", "-lgmp"]


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def main():
    cxx_path = os.path.realpath(shutil.which(CXX) or CXX); ver = subprocess.run([CXX, "--version"], capture_output=True, text=True).stdout.strip()
    cmd = [CXX] + FLAGS + ["-o", LIB, SRC]; t = time.monotonic(); r = subprocess.run(cmd, capture_output=True, text=True); dt = time.monotonic() - t
    libs = {}
    for name in ("mpfr/lib/libmpfr.6.dylib", "gmp/lib/libgmp.10.dylib"):
        p = os.path.join(PREFIX, "opt", name)
        if os.path.exists(p):
            libs[p] = sha(p)
    rec = {"compiler": CXX, "compiler_executable_path": cxx_path, "compiler_executable_sha256": sha(cxx_path) if os.path.exists(cxx_path) else None, "compiler_version": ver, "flags": FLAGS, "command": cmd, "returncode": r.returncode, "stderr": r.stderr[-4000:], "build_wall_s": dt,
           "source": os.path.relpath(SRC, HERE), "source_sha256": sha(SRC), "binary": os.path.relpath(LIB, HERE), "binary_sha256": sha(LIB) if r.returncode == 0 and os.path.exists(LIB) else None, "linked_libraries_sha256": libs, "platform": platform.platform(), "machine": platform.machine(), "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "arithmetic": "general route: outward MPFR intervals (RNDD/RNDU) in native pools; optional route: binary64 nearest-even (admitted per plan by the executor's range/depth proof); no division; -ffp-model=strict -ffp-contract=off"}
    json.dump(rec, open(os.path.join(HERE, "gbidi", "BUILD_RECORD.json"), "w"), indent=1); print(json.dumps({k: rec[k] for k in ("returncode", "binary_sha256", "build_wall_s")}))
    if r.returncode != 0:
        print(r.stderr, file=sys.stderr); sys.exit(1)


if __name__ == "__main__":
    main()
