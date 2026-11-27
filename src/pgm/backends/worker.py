"""Private, process-isolated adapters for the retained certified solvers.

An absolute monotonic deadline and a per-attempt PAC allowance come from the
public controller.  This worker does not grant a fresh request-level risk
budget.  The controller enforces process-tree memory and terminal wall time;
these adapters additionally reduce each backend's cooperative memory ceilings.

The old modules use bare imports and mutable module policies.  Isolation keeps
those implementation details out of the supported Python API and prevents one
backend's settings or temporary state from leaking into another attempt.
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout
from fractions import Fraction
import hashlib
import importlib
import json
import math
from pathlib import Path
import sys
import tempfile
import time
import traceback

F = Fraction
WALL_TOKEN = '"__PGM_WORKER_WALL__"'
DETERMINISTIC_LABELS = {"EXACT", "DETERMINISTIC", "DETERMINISTIC_RESIDUAL"}
PAC_LABELS = {"PAC", "PAC_EB", "PAC_MARKOV", "PAC_MARKOV_RESPONSE"}


class AdapterRefused(Exception):
    def __init__(self, kind: str, reason: str):
        self.kind, self.reason = kind, reason
        super().__init__(reason)


def _code_root() -> Path:
    """Resolve the source/install layout without a creator-workstation path."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "code"
        if (candidate / "cex" / "newarm" / "core.py").is_file():
            return candidate
    # Installed distributions map the retained packages alongside ``pgm``.
    import importlib.util
    spec = importlib.util.find_spec("cex.newarm")
    if spec and spec.submodule_search_locations:
        return Path(next(iter(spec.submodule_search_locations))).parent.parent
    raise AdapterRefused("INSTALLATION", "retained inference packages are absent")


def _install_paths() -> None:
    code = _code_root()
    for suffix in ("", "cex/newarm", "cex/blockres", "cex/hp"):
        path = str(code / suffix)
        if path not in sys.path:
            sys.path.insert(0, path)


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def read_inventory(path: Path, memory_bytes: int) -> tuple[list[tuple[int, int]], dict]:
    """Read the original singleton inventory before any optional solver refuses.

    This reads only the model header and evidence for the inventory.  The solver
    still validates every factor and value before claiming an answer.
    """
    def tokens(stream):
        for line in stream:
            yield from line.split()
    with path.open() as stream:
        ts = tokens(stream)
        kind = next(ts)
        if kind not in {"MARKOV", "BAYES"}:
            raise ValueError("expected UAI MARKOV or BAYES")
        n = int(next(ts))
        if n < 0 or n * 256 > memory_bytes:
            raise AdapterRefused("MEMORY", "original variable inventory exceeds memory allowance")
        cards = [int(next(ts)) for _ in range(n)]
        if any(c < 1 for c in cards):
            raise ValueError("invalid cardinality")
        if sum(cards) * 256 > memory_bytes:
            raise AdapterRefused("MEMORY", "original query inventory exceeds memory allowance")
    ep = Path(str(path) + ".evid")
    eb = ep.read_bytes() if ep.exists() else b"0"
    ts = iter(eb.split())
    count = int(next(ts))
    if not 0 <= count <= n:
        raise ValueError("invalid evidence count")
    evidence = {}
    for _ in range(count):
        v, a = int(next(ts)), int(next(ts))
        if not 0 <= v < n or not 0 <= a < cards[v] or v in evidence:
            raise ValueError("invalid or duplicate evidence")
        evidence[v] = a
    if next(ts, None) is not None:
        raise ValueError("trailing evidence data")
    inventory = [(v, a) for v, card in enumerate(cards) if v not in evidence for a in range(card)]
    return inventory, {"model_sha256": _sha(path), "evidence_sha256": hashlib.sha256(eb).hexdigest()}


def _empty_rows(inventory):
    return [{"var": v, "variable": v, "state": a, "guarantee": "NOT_PUBLISHED"} for v, a in inventory]


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise AdapterRefused("DEADLINE", "absolute attempt deadline reached")
    return remaining


def _memory_policy(module, memory_bytes: int) -> None:
    """Only lower declared backend ceilings; never increase an inherited cap."""
    headroom = getattr(module, "PROCESS_HEADROOM_BYTES", 160 << 20)
    usable = max(0, memory_bytes - headroom)
    for name in ("USABLE_BYTES",):
        if hasattr(module, name):
            setattr(module, name, min(getattr(module, name), usable))
    if hasattr(module, "CEX_CAP_BYTES"):
        module.CEX_CAP_BYTES = min(module.CEX_CAP_BYTES, memory_bytes)
    if hasattr(module, "CONSTRUCTOR_BYTES"):
        module.CONSTRUCTOR_BYTES = min(module.CONSTRUCTOR_BYTES, usable)


def _structural(args) -> dict:
    core = importlib.import_module("core")
    _memory_policy(core, args.memory_bytes)
    _remaining(args.deadline)
    model, binding = core.read_uai(args.input)
    result = core.solve(model, deadline=args.deadline, route=args.structural_route)
    rows = []
    for v, (bounds, points) in enumerate(zip(result["intervals"], result["points"])):
        if v in model.get("evidence", {}):
            continue
        for a, ((lo, hi), point) in enumerate(zip(bounds, points)):
            rows.append({"var": v, "state": a, "lo": str(lo), "hi": str(hi),
                         "point": str(point), "guarantee": "EXACT" if lo == hi else "DETERMINISTIC"})
    return {"outcome": "COMPLETE", "answers": rows, "binding": binding,
            "positive_mass_witness": True, "Z": None,
            "mechanism": {"route": "structural", "structural_route": args.structural_route,
                          "stats": result.get("stats"), "certificate": result.get("certificate"),
                          "reduction_certificate": result.get("reduction_certificate"),
                          "decoder": result.get("decoder"),
                          "normalizer": "not supplied by this marginal-only adapter"}}


def _block(args) -> dict:
    module = importlib.import_module("integrated")
    _memory_policy(module, args.memory_bytes)
    # The accepted engine's benchmarked configuration is passed EXPLICITLY (pgm.policies.accepted.ACCEPTED_CONFIGURATION);
    # integrated.solve's own defaults (schedule 'baseline') do not reproduce the accepted arm.  The frozen experimental
    # portfolio used the same targeted configuration for this adapter.
    cfg = dict(args.configuration or {})
    route_by_mode = cfg.get("route_by_mode") or {"auto": "auto", "deterministic": "exact", "exact": "exact"}
    return module.solve(str(args.input), _remaining(args.deadline), seed=args.seed,
                        eps=args.epsilon, delta=args.delta, schedule=cfg.get("schedule", "targeted"),
                        route=route_by_mode.get(args.mode, "exact"), proposal=cfg.get("proposal", "mb"),
                        table_cap=int(cfg.get("table_cap", 1 << 18)), enum_cap=int(cfg.get("enum_cap", 1 << 16)),
                        mb_cap=int(cfg.get("mb_cap", 1 << 24)), batch=int(cfg.get("batch", 1024)), crosscheck=bool(cfg.get("crosscheck", True)))


def _quotient(args) -> dict:
    module = importlib.import_module("unified_pac_planner")
    core = importlib.import_module("core")
    _memory_policy(module.CE, args.memory_bytes)
    _memory_policy(module.PA.IG, args.memory_bytes)
    _memory_policy(core, args.memory_bytes)
    begin = time.monotonic()
    remaining = _remaining(args.deadline)
    model, binding = core.read_uai(args.input)
    planner = module.UPlanner(model, binding, remaining, eps=args.epsilon, delta=args.delta,
                              admission_stop_s=max(0.0, remaining - 0.35), t_start=begin,
                              seed=args.seed, pac=args.mode == "auto", lifted=True, envelope="RMAX", glob="global")
    result = planner.run()
    result["binding"] = binding
    return result


def _response(args) -> dict:
    if args.mode != "auto":
        raise AdapterRefused("INELIGIBLE", "response backend requires a PAC-permitted request")
    module = importlib.import_module("spectral_heatbath_run")
    _memory_policy(module.CE, args.memory_bytes)
    _memory_policy(importlib.import_module("integrated"), args.memory_bytes)
    remaining = _remaining(args.deadline)
    # The existing runner is a CLI with its own finalizer.  Capture its raw
    # result privately, then apply the controller's absolute publication check.
    with tempfile.TemporaryDirectory(prefix="pgm-response-") as directory:
        raw = Path(directory) / "result.json"
        previous = sys.argv
        sys.argv = ["spectral_heatbath_run", "--input", str(args.input), "--output", str(raw),
                    "--budget", str(remaining), "--admission-stop", str(max(0.0, remaining - 0.35)),
                    "--epsilon", str(args.epsilon), "--delta", str(args.delta), "--seed", str(args.seed),
                    "--policy", "revised", "--response"]
        try:
            module.main()
        except SystemExit as e:
            if not raw.exists():
                raise AdapterRefused("BACKEND_EXIT", f"response runner exited with {e.code}") from e
        finally:
            sys.argv = previous
        return json.loads(raw.read_text())


BACKENDS = {"structural": _structural, "block": _block, "quotient": _quotient, "response": _response}


def normalize_result(result: dict, inventory, binding, epsilon: F) -> dict:
    """Validate and normalize a backend result without strengthening its claim."""
    if result.get("binding") and result["binding"] != binding:
        raise AdapterRefused("CERTIFICATE_DEFECT", "backend binding differs from original input")
    expected = set(inventory)
    got = {}
    valid = []
    for raw in result.get("answers") or []:
        key = (raw.get("variable", raw.get("var")), raw.get("state"))
        if key not in expected or key in got:
            raise AdapterRefused("CERTIFICATE_DEFECT", "backend returned unexpected or duplicate coordinate")
        got[key] = raw
    for v, a in inventory:
        raw = got.get((v, a), {})
        label = raw.get("guarantee", "NOT_PUBLISHED")
        row = {"var": v, "variable": v, "state": a, "guarantee": label}
        if label != "NOT_PUBLISHED":
            if label not in DETERMINISTIC_LABELS | PAC_LABELS:
                raise AdapterRefused("CERTIFICATE_DEFECT", f"unrecognized guarantee {label}")
            try:
                lo, hi, point = F(raw["lo"]), F(raw["hi"]), F(raw["point"])
            except (KeyError, ValueError, ZeroDivisionError) as e:
                raise AdapterRefused("CERTIFICATE_DEFECT", "malformed probability enclosure") from e
            if not (0 <= lo <= point <= hi <= 1):
                raise AdapterRefused("CERTIFICATE_DEFECT", "invalid probability enclosure")
            if label == "EXACT" and not lo == hi == point:
                raise AdapterRefused("CERTIFICATE_DEFECT", "EXACT label has nonzero enclosure width")
            if max(point - lo, hi - point) > epsilon:
                # A legacy backend has a fixed tolerance.  Its truthful wider
                # enclosure cannot be promoted to this request's answer.
                row = {"var": v, "variable": v, "state": a, "guarantee": "NOT_PUBLISHED"}
            else:
                row.update(lo=str(lo), hi=str(hi), point=str(point))
                if label in PAC_LABELS:
                    row["guarantee"] = "PAC"
                elif label != "EXACT":
                    row["guarantee"] = "DETERMINISTIC"
        valid.append(row)
    # Coordinatewise points need not sum to one in the inherited contract,
    # but the delivered interval box must admit a probability simplex.
    groups = {}
    for row in valid:
        groups.setdefault(row["var"], []).append(row)
    for rows in groups.values():
        lower = sum((F(r["lo"]) for r in rows if r["guarantee"] != "NOT_PUBLISHED"), F(0))
        upper = sum((F(r["hi"]) if r["guarantee"] != "NOT_PUBLISHED" else F(1) for r in rows), F(0))
        if not lower <= 1 <= upper:
            raise AdapterRefused("CERTIFICATE_DEFECT", "probability interval box misses the simplex")
    mechanism = result.get("mechanism") or {}
    witness = result.get("positive_mass_witness", mechanism.get("positive_mass_witness"))
    published = sum(r["guarantee"] != "NOT_PUBLISHED" for r in valid)
    if published and witness is not True:
        raise AdapterRefused("CERTIFICATE_DEFECT", "published rows lack a positive-mass witness")
    labels = {r["guarantee"] for r in valid if r["guarantee"] != "NOT_PUBLISHED"}
    if published < len(inventory):
        guarantee = "PARTIAL" if published else "NONE"
    elif "PAC" in labels:
        guarantee = "PAC"
    elif "DETERMINISTIC" in labels:
        guarantee = "DETERMINISTIC"
    else:
        guarantee = "EXACT" if witness is True else "NONE"
    outcome = result.get("outcome", "REFUSED")
    if published == len(inventory) and witness is True:
        outcome = "COMPLETE"
    elif outcome in {"COMPLETE", "EXACT"}:
        outcome = "PARTIAL" if published else "REFUSED"
    out = dict(result)
    out.update(answers=valid, K=len(inventory), published=published, outcome=outcome,
               guarantee=guarantee, binding=binding, positive_mass_witness=witness)
    return out


def suppressed(result: dict, inventory, kind="DEADLINE", reason="absolute attempt deadline reached") -> dict:
    out = dict(result)
    out.update(answers=_empty_rows(inventory), enclosures=[], published=0,
               K=len(inventory), guarantee="NONE", outcome=kind,
               hard_deadline_respected=False if kind == "DEADLINE" else True)
    out["mechanism"] = dict(result.get("mechanism") or {}, adapter_refusal={"kind": kind, "reason": reason},
                            suppressed_rows=result.get("published", 0))
    for name in ("max_width", "max_radius", "max_published_width", "max_published_radius"):
        if name in out:
            out[name] = None
    return out


def write_result(path: Path, result: dict, inventory, deadline: float, started: float) -> dict:
    """Stage both payloads before the authoritative pre-commit deadline sample."""
    result = dict(result, wall_s="__PGM_WORKER_WALL__", hard_deadline_respected=True)
    late_result = suppressed(result, inventory)
    normal = json.dumps(result, default=str, separators=(",", ":"))
    late = json.dumps(late_result, default=str, separators=(",", ":"))
    if normal.count(WALL_TOKEN) != 1 or late.count(WALL_TOKEN) != 1:
        raise ValueError("ambiguous worker timestamp placeholder")
    path.parent.mkdir(parents=True, exist_ok=True)
    now = time.monotonic()
    selected = result if now <= deadline else late_result
    payload = (normal if now <= deadline else late).replace(WALL_TOKEN, "%.9e" % (now - started), 1)
    # The parent additionally requires worker termination before the hard
    # request deadline; a write finishing late cannot become a public success.
    with path.open("w") as stream:
        stream.write(payload)
    return selected


def run(args) -> dict:
    started = time.monotonic()
    inventory, binding = [], {}
    result = {"backend": args.backend, "outcome": "REFUSED", "answers": [], "mechanism": {}}
    try:
        inventory, binding = read_inventory(args.input, args.memory_bytes)
        result["binding"] = binding
        _remaining(args.deadline)
        _install_paths()
        # Existing runners print diagnostics; keep stdout available for one
        # adapter record and retain backend output in the worker's stderr log.
        with redirect_stdout(sys.stderr):
            result = BACKENDS[args.backend](args)
        result = normalize_result(result, inventory, binding, args.epsilon)
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
                  configuration=getattr(args, "configuration", None))
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
    args = ap.parse_args(argv)
    args.configuration = json.loads(args.configuration) if args.configuration else None
    if not math.isfinite(args.deadline) or args.epsilon <= 0 or not 0 <= args.delta < 1 or (args.delta == 0 and args.backend != "structural" and args.mode == "auto") or args.memory_mib <= 0:
        ap.error("finite deadline, positive epsilon/memory and a positive PAC allowance when sampling are required")
    args.memory_bytes = args.memory_mib << 20
    run(args)


if __name__ == "__main__":
    main()
