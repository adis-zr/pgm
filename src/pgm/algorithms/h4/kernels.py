"""Explicit host builds for the fixed H4 arithmetic specialist.

Sources ship with the package; historical binaries never participate in lookup.
Builds and their checked records live under PGM_NATIVE_CACHE/h4 or the user's
cache, never beside the Python modules. No inference call compiles implicitly.
"""
from __future__ import annotations

import argparse
import fcntl
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import tempfile

from ...specialists.errors import SpecialistUnavailable


KERNELS = ("h4point", "h4rect", "h4pcheck")
FLAGS = ("-O2", "-std=c++17", "-fno-fast-math", "-ffp-contract=off")
SOURCE_DIR = Path(__file__).resolve().parent / "native"


class KernelUnavailable(SpecialistUnavailable):
    """A missing or invalid H4 kernel, catchable through the public specialist contract."""


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@lru_cache(maxsize=32)
def _compiler_sha(path, size, modified_ns, changed_ns):
    # Cache only within this process and this filesystem incarnation. Resolving
    # the command again detects PATH or symlink changes under the same CXX name.
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _compiler_files(command):
    files = []
    for index, token in enumerate(command):
        resolved = None if token.startswith("-") else shutil.which(token)
        if resolved is None:
            if index == 0:
                files.append(dict(argument=token, resolved=None, binary_sha256=None))
            continue
        path = Path(resolved).resolve()
        stat = path.stat()
        files.append(dict(argument=token, resolved=str(path),
                          binary_sha256=_compiler_sha(str(path), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)))
    return files


def cache_root():
    configured = os.environ.get("PGM_NATIVE_CACHE")
    if configured:
        root = Path(configured).expanduser()
    else:
        base = os.environ.get("XDG_CACHE_HOME")
        root = (Path(base).expanduser() if base else Path.home() / ".cache") / "pgm" / "native_cache"
    root = (root / "h4").resolve()
    package = Path(__file__).resolve().parents[2]
    if root.is_relative_to(package):
        raise KernelUnavailable("H4 build cache must be outside the pgm source package")
    return root


def _identity():
    compiler = shlex.split(os.environ.get("CXX", "c++"))
    if not compiler:
        raise KernelUnavailable("CXX must name a C++ compiler")
    includes, libraries = [], []
    if platform.system() == "Darwin":
        for name in ("gmp", "mpfr"):
            prefix = Path("/opt/homebrew/opt") / name
            if (prefix / "include").is_dir():
                includes.append("-I" + str(prefix / "include"))
            if (prefix / "lib").is_dir():
                libraries.append("-L" + str(prefix / "lib"))
    return dict(version=1, system=platform.system(), machine=platform.machine(),
                compiler=compiler, compiler_files=_compiler_files(compiler),
                flags=list(FLAGS), includes=includes, libraries=libraries,
                include_environment={name: os.environ.get(name, "") for name in
                                     ("CPATH", "CPLUS_INCLUDE_PATH", "LIBRARY_PATH")},
                sources={name + ".cpp": _sha(SOURCE_DIR / (name + ".cpp")) for name in KERNELS})


def build_dir():
    identity = _identity()
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    return cache_root() / digest


def _valid_record(directory, name, identity):
    binary, record_path = directory / name, directory / (name + ".json")
    try:
        record = json.loads(record_path.read_text())
        if (record.get("identity") == identity and record.get("kernel") == name
                and record.get("binary_sha256") == _sha(binary)
                and os.access(binary, os.X_OK) and record.get("probes_ok") is True):
            return record
    except (OSError, ValueError, TypeError):
        pass
    return None


def available():
    identity, directory = _identity(), build_dir()
    missing = [name for name in KERNELS if _valid_record(directory, name, identity) is None]
    return dict(available=not missing, build_dir=str(directory), missing_kernels=missing,
                scope="fixed H4 arithmetic specialist; not a generic UAI backend")


def kernel_path(name):
    if name not in KERNELS:
        raise ValueError("unknown H4 kernel: " + str(name))
    identity, directory = _identity(), build_dir()
    if _valid_record(directory, name, identity) is None:
        raise KernelUnavailable("H4 kernel %s is not built for this source/host; run python -m pgm.algorithms.h4.kernels" % name)
    return directory / name


def build_all(names=KERNELS, *, timeout_s=120):
    """Explicit setup, with strict floating-point flags and durable build records."""
    names = tuple(names)
    if not names or any(name not in KERNELS for name in names):
        raise ValueError("choose one or more declared H4 kernels")
    identity, directory = _identity(), build_dir()
    if identity["compiler_files"][0]["resolved"] is None:
        raise KernelUnavailable("CXX compiler is unavailable: " + identity["compiler"][0])
    directory.mkdir(parents=True, exist_ok=True)
    records = {}
    compiler_version = None
    with (directory / ".build.lock").open("a") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        for name in names:
            record = _valid_record(directory, name, identity)
            if record is None:
                if compiler_version is None:
                    version = subprocess.run([*identity["compiler"], "--version"], capture_output=True,
                                             text=True, timeout=min(timeout_s, 10))
                    if version.returncode:
                        raise KernelUnavailable("CXX version probe failed: " + version.stderr[-1000:])
                    compiler_version = version.stdout.strip()
                fd, temporary = tempfile.mkstemp(prefix=name + ".", dir=directory)
                os.close(fd)
                target = Path(temporary)
                command = [*identity["compiler"], *FLAGS]
                if name == "h4rect":
                    command.extend(identity["includes"])
                command.extend([str(SOURCE_DIR / (name + ".cpp")), "-o", str(target)])
                if name == "h4rect":
                    command.extend([*identity["libraries"], "-lmpfr", "-lgmp"])
                try:
                    built = subprocess.run(command, capture_output=True, text=True, timeout=timeout_s)
                    if built.returncode:
                        raise KernelUnavailable("H4 %s compilation failed: %s" % (name, built.stderr[-3000:]))
                    probes = None
                    if name != "h4rect":
                        checked = subprocess.run([str(target), "--probes-only"], capture_output=True,
                                                 text=True, timeout=min(timeout_s, 30))
                        if checked.returncode:
                            raise KernelUnavailable("H4 %s floating-point probes failed: %s" % (name, checked.stderr[-1000:]))
                        probes = json.loads(checked.stdout)
                        if (probes.get("env") != "ok" or not probes.get("probes")
                                or any(p.get("ok") is not True for p in probes["probes"])):
                            raise KernelUnavailable("H4 %s returned incomplete floating-point probes" % name)
                    record = dict(kernel=name, identity=identity, command=command,
                                  compiler_version=compiler_version,
                                  binary_sha256=_sha(target), probes_ok=True, probes=probes,
                                  note="h4rect has no standalone probe mode; its directed MPFR path is qualified by witness controls")
                    if _identity() != identity:
                        raise KernelUnavailable("H4 sources or toolchain changed during compilation")
                    os.replace(target, directory / name)
                    staged_record = directory / (name + ".json.tmp")
                    with staged_record.open("w") as stream:
                        json.dump(record, stream, indent=2); stream.write("\n"); stream.flush(); os.fsync(stream.fileno())
                    os.replace(staged_record, directory / (name + ".json"))
                finally:
                    if target.exists():
                        target.unlink()
            records[name] = record
    return dict(build_dir=str(directory), kernels=records, all_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kernel", action="append", choices=KERNELS)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--output-record", type=Path)
    args = parser.parse_args(argv)
    result = build_all(args.kernel or KERNELS, timeout_s=args.timeout)
    if args.output_record is not None:
        args.output_record.parent.mkdir(parents=True, exist_ok=True)
        args.output_record.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
