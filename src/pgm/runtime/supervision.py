"""Run the retained owned-tree supervisor with no post-deadline grace.

This module deliberately imports no inference engine.  The worker launched by
the supervisor owns a separate process group; nested supervisors register in
the same ownership directory, including when this API is itself supervised.
"""
from __future__ import annotations

from pathlib import Path
import sys


def implementation():
    # Source checkout and installed wheel use the same retained implementation (the owned-tree supervisor).
    code = Path(__file__).resolve().parents[3] / "code"
    if code.is_dir() and str(code) not in sys.path:
        sys.path.insert(0, str(code))
    from gbidi import supervise
    return supervise


def main():
    supervise = implementation()
    supervise.GRACE_S = 0.0
    supervise.main()


if __name__ == "__main__":
    main()
