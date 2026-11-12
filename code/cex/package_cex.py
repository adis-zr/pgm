"""Package the CERTIFIED EXECUTOR PASS deliverable (11 Nov 2026): one self-contained archive (code/cex source trees incl. kernel sources, build records and
qualification outputs; the complete run directory incl. ledger, campaigns, locked plans, kernel versions and closeout; the received prompt and the packet's
MANIFEST_SHA256.json + THEORY.md as identity of the inputs; the unchanged supervisor source), an integrity record written OUTSIDE the archive (sha256,
bytes, member count, central-directory and member tests, first-bad), and the packaging job's own supervisory receipt as a sidecar written by the caller.
Excluded: compiled binaries / native caches / __pycache__ (host-specific; rebuild from source with the pinned flags in cex_build.json), the 35 MB
historical evidence JSON of the packet (identity kept via MANIFEST_SHA256.json).
    python cex/package_cex.py RUN_DIR OUT.zip"""
import os, sys, json, time, hashlib, zipfile, tempfile, subprocess
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # code/
PACKET = "/Users/adis/Workspace/pgm/docs/handoff-received-2026-11-11-certified-executor"
SKIP_DIRS = ("__pycache__", "native_cache")
SKIP_SUFFIX = (".dylib", ".so", ".pyc")


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main(D, out):
    D = os.path.abspath(D); out = os.path.abspath(out)
    if os.path.exists(out):
        raise SystemExit("refuse: %s exists" % out)
    hashes = {}; n = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        def add(path, arc):
            nonlocal n
            z.write(path, arc); hashes[arc] = sha(path); n += 1
        def add_tree(root, arcroot, skip_binaries=True):
            for dp, dns, fns in os.walk(root):
                dns[:] = sorted(d for d in dns if d not in SKIP_DIRS)
                for fn in sorted(fns):
                    if skip_binaries and fn.endswith(SKIP_SUFFIX):
                        continue
                    p = os.path.join(dp, fn); add(p, os.path.join(arcroot, os.path.relpath(p, root)))
        add_tree(os.path.join(HERE, "cex"), "code/cex")
        add_tree(D, "run_dir/" + os.path.basename(D))
        add(os.path.join(HERE, "gbidi", "supervise.py"), "code/gbidi/supervise.py")
        add(os.path.join(PACKET, "CLAUDE_CERTIFIED_EXECUTOR_PASS_PROMPT_AND_CONTEXT_2026-11-11.txt"), "received/CLAUDE_CERTIFIED_EXECUTOR_PASS_PROMPT_AND_CONTEXT_2026-11-11.txt")
        for REVIEW, tag in (("/Users/adis/Workspace/pgm/docs/review-received-2026-11-11-certified-executor", "received_review"), ("/Users/adis/Workspace/pgm/docs/review-received-2026-11-11-certified-executor-repair", "received_review2")):
          sub_root = "evidence/executor_adversarial_review_2026-11-11" if tag == "received_review" else "evidence/executor_repair_review_2026-11-11"
          for f in sorted(os.listdir(REVIEW)):
            if f.endswith(".txt") and os.path.isfile(os.path.join(REVIEW, f)): add(os.path.join(REVIEW, f), tag + "/" + f)
          d0 = os.path.join(REVIEW, sub_root)
          for sub in (sorted(os.listdir(d0)) if os.path.isdir(d0) else []):
            d = os.path.join(d0, sub)
            if os.path.isdir(d):
                for dp, dns, fns in os.walk(d):
                    dns[:] = sorted(x for x in dns if x not in ("newarm", "newarm_copy", "__pycache__"))      # the reviewer's adapted source copies are excluded (their identity is in the review's manifest)
                    for fn in sorted(fns):
                        if fn.endswith((".md", ".py", ".json", ".cpp", ".txt", ".stderr", ".stdout", ".gz", ".uai")): add(os.path.join(dp, fn), tag + "/evidence/" + sub + "/" + os.path.relpath(os.path.join(dp, fn), d))
        for f in ("MANIFEST_SHA256.json", "THEORY.md"):
            p = os.path.join(PACKET, "packet", f)
            if os.path.exists(p):
                add(p, "received/packet/" + f)
        git = subprocess.run(["git", "-C", HERE, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        branch = subprocess.run(["git", "-C", HERE, "branch", "--show-current"], capture_output=True, text=True).stdout.strip()
        z.writestr("MEMBER_SHA256.json", json.dumps({"git_head_at_packaging": git, "branch": branch, "members": hashes}, indent=1, sort_keys=True))
    with zipfile.ZipFile(out) as z:
        bad = z.testzip(); names = z.namelist()
    tmp = tempfile.mkdtemp(prefix="cex_pkg_")
    with zipfile.ZipFile(out) as z:
        z.extractall(tmp)
    extracted_ok = all(sha(os.path.join(tmp, a)) == h for a, h in hashes.items())
    rec = {"zip": out, "bytes": os.path.getsize(out), "sha256": sha(out), "members": n + 1, "namelist": len(names), "testzip_first_bad": bad, "central_directory_readable": True,
           "extraction_member_hashes_verified": extracted_ok, "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "git_head_at_packaging": git, "branch": branch,
           "excluded": "compiled binaries, native caches, __pycache__ (host-specific; rebuild from source with cex_build.json flags); packet prototype/inputs/historical_evidence (identity via received/packet/MANIFEST_SHA256.json; inputs sha256 in run_dir INPUTS_RECEIVED_SHA256.txt)",
           "note": "the packaging job's own supervisor receipt lands AFTER this record: see the receipt sidecar next to the zip, written by the caller"}
    json.dump(rec, open(os.path.join(D, "PACKAGE_RECORD_CEX.json"), "w"), indent=1)
    json.dump(rec, open(out + ".integrity.json", "w"), indent=1)
    print(json.dumps(rec, indent=1))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
