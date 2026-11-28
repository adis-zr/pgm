"""The isolated worker: one attempt of one backend adapter under the controller's absolute deadline.

The controller passes an absolute monotonic deadline, this attempt's PAC allowance (the policy's share, never a
fresh request-level budget), the explicit backend configuration and the expected source binding.  The worker
parses the source EXACTLY ONCE (``pgm.model.uai.load_bound``), refuses a binding mismatch, dispatches to the
adapter, normalizes the result through the common publication boundary and commits with the staged
late-suppression payload.  Isolation remains because the retained implementations use mutable module policies
(module-level ceilings lowered per attempt); nothing here or in the adapters manipulates ``sys.path`` or ``sys.argv``.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager, redirect_stdout
from fractions import Fraction
import json
import math
from pathlib import Path
import sys
import time
import traceback

from ..model.uai import SourceRefused, load_bound, read_uai
from ..validation.publication import (AdapterRefused, DETERMINISTIC_LABELS, PAC_LABELS, WALL_TOKEN, normalize_result,
                                      suppressed, write_result, empty_rows as _empty_rows)
from .base import AdapterContext
from . import structural, block, quotient, response

F = Fraction
BACKENDS = {"structural": structural.run, "block": block.run, "quotient": quotient.run, "response": response.run}


@contextmanager
def _record_stage(timings, name):
    """Diagnostic elapsed time only; all stages precede the publication clock.

    perf_counter is separate from the hard-deadline monotonic reads so timing
    instrumentation cannot alter the clock-read protocol used by controls.
    A refused stage records its actual consumed time as well.
    """
    started = time.perf_counter()
    try:
        yield
    finally:
        timings[name] = time.perf_counter() - started


def read_inventory(path: Path, memory_bytes: int):
    """Compatibility: the original nonobserved inventory and binding of a source (one exact parse)."""
    bound = load_bound(path, memory_bytes=memory_bytes)
    return bound.inventory, bound.binding


def run(args) -> dict:
    started = time.monotonic()
    inventory, binding = [], {}
    timings = {}
    result = {"backend": args.backend, "outcome": "REFUSED", "answers": [], "mechanism": {}}
    try:
        with _record_stage(timings, "source_parse_s"):
            bound = load_bound(args.input, expected_binding=args.expected_binding, memory_bytes=args.memory_bytes)
        inventory, binding = bound.inventory, bound.binding
        result["binding"] = binding
        context = AdapterContext(deadline=args.deadline, epsilon=args.epsilon, delta=args.delta, seed=args.seed,
                                 memory_bytes=args.memory_bytes, mode=args.mode, structural_route=args.structural_route,
                                 configuration=args.configuration, policy=args.policy)
        context.remaining()
        # Existing runners print diagnostics; keep stdout available for one
        # adapter record and retain backend output in the worker's stderr log.
        with _record_stage(timings, "adapter_s"), redirect_stdout(sys.stderr):
            result = BACKENDS[args.backend](bound, context)
        with _record_stage(timings, "normalization_s"):
            result = normalize_result(result, inventory, binding, args.epsilon)
    except SourceRefused as e:
        if e.bound is not None:
            inventory, binding = e.bound.inventory, e.bound.binding; result["binding"] = binding
        result = suppressed(result, inventory, e.kind, e.reason)
    except AdapterRefused as e:
        result = suppressed(result, inventory, e.kind, e.reason)
    except Exception as e:
        kind = getattr(e, "kind", None)
        if isinstance(e, TimeoutError):
            kind = "DEADLINE"
        elif isinstance(e, MemoryError):
            kind = "MEMORY"
        elif isinstance(e, ValueError) and str(e) == "ZERO_EVIDENCE":
            kind = "ZERO_EVIDENCE"
        elif isinstance(e, (ValueError, AssertionError, StopIteration, OSError)) and not kind:
            kind = "INVALID_TASK" if not binding else "BACKEND_REFUSED"
        kind = kind or "BACKEND_REFUSED"
        result = suppressed(result, inventory, str(kind), str(e)[:500])
        if kind == "ZERO_EVIDENCE":
            result["positive_mass_witness"] = False
        result["mechanism"]["exception_type"] = type(e).__name__
        result["mechanism"]["traceback"] = traceback.format_exc()[-3000:]
    result.update(backend=args.backend, input=str(args.input.resolve()), binding=binding,
                  epsilon=str(args.epsilon), delta=str(args.delta), seed=args.seed,
                  memory_mib=args.memory_mib, deadline_monotonic=args.deadline, policy=getattr(args, "policy", None),
                  configuration=getattr(args, "configuration", None), runtime_timings=timings)
    return write_result(args.output, result, inventory, args.deadline, started)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--backend", choices=tuple(BACKENDS), required=True)
    ap.add_argument("--input", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--deadline", type=float, required=True)
    ap.add_argument("--epsilon", type=F, default=F(1, 200))
    ap.add_argument("--delta", type=F, default=F(1, 10**6))
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--memory-mib", type=int, default=3072)
    ap.add_argument("--mode", choices=("auto", "exact", "deterministic"), default="auto")
    ap.add_argument("--structural-route", "--route", choices=("auto", "stream", "support", "dag"), default="auto")
    ap.add_argument("--policy", default="accepted", help="the public policy that selected this attempt (recorded)")
    ap.add_argument("--configuration", default=None, help="JSON: the explicit backend configuration selected by the policy")
    ap.add_argument("--expected-binding", default=None, help="JSON: the controller's source binding (model_sha256 / evidence_sha256); a mismatch is a typed BINDING refusal")
    args = ap.parse_args(argv)
    args.configuration = json.loads(args.configuration) if args.configuration else None
    args.expected_binding = json.loads(args.expected_binding) if args.expected_binding else None
    if not math.isfinite(args.deadline) or args.epsilon <= 0 or not 0 <= args.delta < 1 or (args.delta == 0 and args.backend != "structural" and args.mode == "auto") or args.memory_mib <= 0:
        ap.error("finite deadline, positive epsilon/memory and a positive PAC allowance when sampling are required")
    args.memory_bytes = args.memory_mib << 20
    run(args)


if __name__ == "__main__":
    main()
