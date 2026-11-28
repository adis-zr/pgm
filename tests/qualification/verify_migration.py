#!/usr/bin/env python3
"""Verify the complete-layout migration inventory against git and destination files.

Run from any directory: python tests/qualification/verify_migration.py.
This reads source bytes only; it does not run inference or modify records.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess

MANIFEST = Path("documentation/migration/complete-layout/MIGRATION.json")
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


def _git_blobs(root, commit, paths):
    requests = "".join(f"{commit}:{path}\n" for path in paths).encode()
    output = subprocess.check_output(["git", "cat-file", "--batch"], input=requests, cwd=root)
    cursor = 0
    hashes = {}
    for path in paths:
        end = output.index(b"\n", cursor)
        header = output[cursor:end].split()
        if len(header) != 3 or header[1] != b"blob":
            raise ValueError(f"baseline blob missing or non-blob: {path}")
        size = int(header[2])
        cursor = end + 1
        hashes[path] = hashlib.sha256(output[cursor:cursor + size]).hexdigest()
        cursor += size + 1
    if cursor != len(output):
        raise ValueError("unexpected trailing git batch output")
    return hashes


def verify(root, manifest=None, *, check_destination_hashes=True):
    """Return explicit issues; malformed/missing files never imply successful migration."""
    root = Path(root).resolve()
    data = json.loads((root / MANIFEST).read_text()) if manifest is None else manifest
    issues = []
    entries = data.get("entries", [])
    old_counts = Counter(row.get("old") for row in entries)
    duplicates = sorted(str(p) for p, n in old_counts.items() if n != 1)
    if duplicates:
        issues.append("duplicate source dispositions: " + ", ".join(duplicates))
    baseline = data.get("old_code_files", {})
    if len(baseline) != 485:
        issues.append("baseline code inventory must contain 485 files")
    actual_code = {p for p in old_counts if isinstance(p, str) and p.startswith("code/")}
    if actual_code != set(baseline):
        issues.append("code dispositions do not exactly cover the baseline inventory")
    if (root / "code").exists():
        issues.append("obsolete code tree still exists")
    paths = list(old_counts)
    valid_paths = all(isinstance(p, str) and not PurePosixPath(p).is_absolute() and ".." not in PurePosixPath(p).parts for p in paths)
    if not valid_paths:
        issues.append("invalid source path")
        return {"all_ok": False, "issues": issues}
    try:
        commit = data["baseline_commit"]
        tree = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", "-z", commit, "--", "code/"], cwd=root)
        tree_paths = {p.decode() for p in tree.split(b"\0") if p}
        if tree_paths != set(baseline):
            issues.append("embedded baseline inventory differs from git tree")
        original = _git_blobs(root, commit, paths)
    except (KeyError, ValueError, subprocess.CalledProcessError) as exc:
        issues.append("cannot verify baseline git objects: " + str(exc))
        original = {}
    for row in entries:
        old, new = row["old"], row.get("new")
        before = row.get("old_sha256")
        if original.get(old) != before:
            issues.append("source hash differs from baseline git blob: " + old)
        if old in baseline and baseline[old] != before:
            issues.append("source hash differs from baseline inventory: " + old)
        if row.get("old_path_removed") and (root / old).exists():
            issues.append("retired source path still exists: " + old)
        if new is None:
            if before != EMPTY_SHA256 or row.get("action") not in ("remove_empty_namespace", "remove_empty_placeholder"):
                issues.append("nonempty source removed without a destination: " + old)
            continue
        if not isinstance(new, str) or PurePosixPath(new).is_absolute() or ".." in PurePosixPath(new).parts:
            issues.append("invalid destination path: " + repr(new))
            continue
        target = root / new
        if not target.is_file():
            issues.append("destination missing: " + new)
            continue
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        frozen = row.get("action") == "archive_byte_identical"
        if check_destination_hashes or frozen:
            if digest != row.get("new_sha256"):
                issues.append("destination hash mismatch: " + new)
        if frozen and (digest != before or not row.get("byte_identical")):
            issues.append("archive is not byte-preserved: " + old)
        for copy in row.get("preserved_copies", []):
            copy_path = copy.get("path")
            if not isinstance(copy_path, str) or PurePosixPath(copy_path).is_absolute() or ".." in PurePosixPath(copy_path).parts:
                issues.append("invalid preserved-copy path: " + repr(copy_path))
                continue
            destination = root / copy_path
            if not destination.is_file():
                issues.append("preserved copy missing: " + copy_path)
                continue
            digest = hashlib.sha256(destination.read_bytes()).hexdigest()
            if digest != before or digest != copy.get("sha256"):
                issues.append("preserved copy differs from original source: " + old)
        module = row.get("canonical_module")
        if module and new != "src/" + module.replace(".", "/") + ".py":
            issues.append("canonical alias replacement path mismatch: " + old)
    return {"all_ok": not issues, "issues": issues, "baseline_code_files": len(baseline),
            "code_dispositions": len(actual_code), "total_dispositions": len(entries),
            "destination_hashes_checked": check_destination_hashes,
            "frozen_archives": sum(r.get("action") == "archive_byte_identical" for r in entries),
            "preserved_copies": sum(len(r.get("preserved_copies", [])) for r in entries)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--allow-later-runtime-edits", action="store_true", help="verify inventory and byte-preserved archives; skip the historical snapshot hash for mutable runtime and campaign files")
    args = parser.parse_args()
    result = verify(args.root, check_destination_hashes=not args.allow_later_runtime_edits)
    print(json.dumps(result, indent=2))
    return 0 if result["all_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
