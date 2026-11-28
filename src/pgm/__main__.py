"""Command-line interface to the same supported Python API."""
import argparse
import json
import os
from pathlib import Path
import tempfile
import time
from . import infer, capabilities
from .policies import names as policy_names


def main(argv=None):
    started = time.monotonic()
    ap = argparse.ArgumentParser(description="Certified singleton inference with automatic structural selection")
    ap.add_argument("--input", type=Path)
    ap.add_argument("--output", type=Path)
    ap.add_argument("--budget", type=float, default=20)
    ap.add_argument("--memory-mib", type=int, default=3072)
    ap.add_argument("--epsilon", default="1/200")
    ap.add_argument("--delta", default="1/1000000")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--mode", choices=["auto","exact","deterministic"], default="auto", help="permitted guarantee")
    ap.add_argument("--policy", choices=policy_names(), default="accepted", help="public scheduling policy (default: the accepted engine through the common contract)")
    ap.add_argument("--query", action="append", metavar="VARIABLE:STATE")
    ap.add_argument("--capabilities", action="store_true")
    a = ap.parse_args(argv)
    if a.capabilities:
        print(json.dumps(capabilities(), indent=2)); return
    if a.input is None or a.output is None:
        ap.error("--input and --output are required")
    queries = [tuple(map(int,q.split(":"))) for q in a.query] if a.query is not None else None
    deadline = started+a.budget
    remaining = deadline-time.monotonic()
    if remaining <= 0:
        ap.error("budget expired during argument parsing")
    result = infer(a.input, budget=remaining, memory_mib=a.memory_mib, epsilon=a.epsilon,
                   delta=a.delta, seed=a.seed, mode=a.mode, queries=queries, policy=a.policy).to_dict()
    # Encode both outcomes before the publication check; a late success is
    # never committed. Outer supervision includes the final file commit.
    late = dict(result, outcome="DEADLINE", guarantee="NONE", published=0, max_published_radius=None, hard_deadline_respected=False,
                answers=[{k:r[k] for k in ("var","variable","state")} | {"guarantee":"NOT_PUBLISHED"} for r in result["answers"]])
    result["wall_s"] = "__PGM_CLI_WALL__"; late["wall_s"] = "__PGM_CLI_WALL__"
    normal_text = json.dumps(result, separators=(",",":")); late_text=json.dumps(late,separators=(",",":"))
    a.output.parent.mkdir(parents=True, exist_ok=True)
    now=time.monotonic()
    text=(normal_text if now <= deadline else late_text).replace('"__PGM_CLI_WALL__"',repr(now-started),1)
    fd,name=tempfile.mkstemp(prefix=".pgm-",dir=a.output.parent)
    try:
        with os.fdopen(fd,"w") as f:f.write(text)
        # If serialization/file writing crosses the bound, replace with the
        # already encoded suppression payload before publishing the path.
        if time.monotonic()>deadline:
            with open(name,"w") as f:f.write(late_text.replace('"__PGM_CLI_WALL__"',repr(time.monotonic()-started),1))
        os.replace(name,a.output)
    finally:
        if os.path.exists(name):os.unlink(name)

if __name__ == "__main__":main()
