"""Build the BIDI native kernel with a RECORDED, frozen compiler contract. Writes bidi/BUILD_RECORD.json (compiler version, exact flags,
source sha256, binary sha256, target) and the shared library bidi/libbidi_kernel.<ext>. Floating-point contract: binary64, round-to-nearest-
even, NO fast-math, NO contraction (FMA), NO reassociation / reciprocal approximations (-ffp-model=strict -ffp-contract=off). Vectorisation
across lanes is permitted: it performs the same IEEE operations on independent lanes.
    python -m bidi.build"""
from __future__ import annotations
import os, sys, json, subprocess, hashlib, platform, time
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(HERE, "bidi", "kernel.cpp")
EXT = "dylib" if sys.platform == "darwin" else "so"
LIB = os.path.join(HERE, "bidi", "libbidi_kernel." + EXT)
CXX = os.environ.get("BIDI_CXX", "clang++")
FLAGS = ["-std=c++17", "-O3", "-ffp-model=strict", "-ffp-contract=off", "-fno-fast-math", "-fno-unsafe-math-optimizations", "-fno-reciprocal-math", "-fno-associative-math",
         "-fvectorize", "-fslp-vectorize", "-fPIC", "-shared", "-Wall", "-Wextra", "-Werror=float-conversion"]


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def main():
    ver = subprocess.run([CXX, "--version"], capture_output=True, text=True).stdout.strip()
    import shutil
    cxx_path = os.path.realpath(shutil.which(CXX) or CXX); cxx_sha = sha(cxx_path) if os.path.exists(cxx_path) else None   # review: the compiler EXECUTABLE is hashed prospectively (the frozen 88afaefe build recorded version/target/flags only)
    cmd = [CXX] + FLAGS + ["-o", LIB, SRC]
    t = time.monotonic(); r = subprocess.run(cmd, capture_output=True, text=True); dt = time.monotonic() - t
    rec = {"compiler": CXX, "compiler_executable_path": cxx_path, "compiler_executable_sha256": cxx_sha, "compiler_version": ver, "flags": FLAGS, "command": cmd, "returncode": r.returncode, "stderr": r.stderr[-4000:], "build_wall_s": dt,
           "source": os.path.relpath(SRC, HERE), "source_sha256": sha(SRC), "binary": os.path.relpath(LIB, HERE), "binary_sha256": sha(LIB) if r.returncode == 0 and os.path.exists(LIB) else None,
           "platform": platform.platform(), "machine": platform.machine(), "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "fp_contract": "off (no FMA contraction)", "fp_model": "strict", "threads": "single worker thread; SIMD across lanes only", "note": "no fast-math, no reassociation, no reciprocal approximation; explicit binary +/* only"}
    json.dump(rec, open(os.path.join(HERE, "bidi", "BUILD_RECORD.json"), "w"), indent=1)
    print(json.dumps({k: rec[k] for k in ("returncode", "binary_sha256", "build_wall_s")}))
    if r.returncode != 0:
        print(r.stderr, file=sys.stderr); sys.exit(1)


if __name__ == "__main__":
    main()
