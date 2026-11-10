"""Build the GENERAL_BIDI_COMPLETE_V3 native kernel (gbidi3/kernel3.cpp -> gbidi3/libgbidi3_kernel.dylib) and write gbidi3/BUILD_RECORD.json
(compiler path + sha256 + version, exact flags, source / binary / linked-library hashes, platform). Same frozen flag set as the repaired V2 kernel:
strict floating-point model, no contraction, no fast-math / reassociation / reciprocal approximations.
    python -m gbidi3.build"""
from __future__ import annotations
import os, sys, json, time, hashlib, platform, subprocess
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
SRC = os.path.join(HERE, "kernel3.cpp"); LIB = os.path.join(HERE, "libgbidi3_kernel.dylib"); REC = os.path.join(HERE, "BUILD_RECORD.json")
FLAGS = ["-std=c++17", "-O2", "-ffp-model=strict", "-ffp-contract=off", "-fno-fast-math", "-fno-unsafe-math-optimizations", "-fno-reciprocal-math", "-fno-associative-math", "-fPIC", "-shared", "-Wall", "-Wextra", "-I/opt/homebrew/include", "-L/opt/homebrew/lib", "-lmpfr", "-lgmp"]
LIBS = ["/opt/homebrew/opt/mpfr/lib/libmpfr.6.dylib", "/opt/homebrew/opt/gmp/lib/libgmp.10.dylib"]


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for ch in iter(lambda: f.read(1 << 20), b""):
            h.update(ch)
    return h.hexdigest()


def main():
    cxx = os.environ.get("CXX", "clang++"); cxx_path = subprocess.run(["which", cxx], capture_output=True, text=True).stdout.strip()
    ver = subprocess.run([cxx, "--version"], capture_output=True, text=True).stdout.strip()
    cmd = [cxx] + FLAGS + ["-o", LIB, SRC]; t0 = time.monotonic(); r = subprocess.run(cmd, capture_output=True, text=True); wall = time.monotonic() - t0
    rec = {"compiler": cxx, "compiler_executable_path": cxx_path, "compiler_executable_sha256": sha(cxx_path) if cxx_path and os.path.exists(cxx_path) else None, "compiler_version": ver, "flags": FLAGS, "command": cmd, "returncode": r.returncode, "stderr": r.stderr[-4000:], "build_wall_s": wall,
           "source": "gbidi3/kernel3.cpp", "source_sha256": sha(SRC), "binary": "gbidi3/libgbidi3_kernel.dylib", "binary_sha256": sha(LIB) if r.returncode == 0 and os.path.exists(LIB) else None,
           "linked_libraries_sha256": {p: sha(p) for p in LIBS if os.path.exists(p)}, "platform": platform.platform(), "machine": platform.machine(), "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "arithmetic": "general route: outward MPFR intervals (RNDD/RNDU); optional route: binary64 nearest-even with per-value exact error labels and a per-operation range check; no division; -ffp-model=strict -ffp-contract=off"}
    json.dump(rec, open(REC, "w"), indent=1); print(json.dumps({"returncode": r.returncode, "binary_sha256": rec["binary_sha256"], "wall_s": round(wall, 3)})); print(r.stderr[-4000:], file=sys.stderr)
    sys.exit(r.returncode)


if __name__ == "__main__":
    main()
