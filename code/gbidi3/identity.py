"""Canonical EXECUTION / TASK identity of GENERAL_BIDI_COMPLETE_V3 (review B3): ONE schema and ONE positive-equality validator shared by the cell, the
executor's checked record, the separate verifier, the manifest, the adapters and the reconciler.

  semantic task       gbidi3.source.TASK_BINDING_FIELDS (raw + legacy canonical + canonical_v2 hashes of model AND evidence, nvars, orig_card,
                      queries_sha256, eps, max_width) + canonical_version
  execution identity  arm, budget_s, full cell config (sorted JSON), rules, protocol, attempt_id, route, and the implementation binding of the route:
                      native routes (binary64 / mpfr / exact_fallback) bind the kernel (binary + source sha256 + flags sha256);
                      python exact routes (exact_scalar / exact_decoder) bind the Python implementation files that computed them.
A missing field is a mismatch, never permission. Only-binary-hash build records are insufficient."""
from __future__ import annotations
import os, json, hashlib

PROTOCOL = "GENERAL_BIDI_COMPLETE_V3/one-pass-validated-executor/v3"
NATIVE_ROUTES = ("binary64", "mpfr", "exact_fallback")
PYTHON_ROUTES = ("exact_scalar", "exact_decoder")
PYTHON_IMPL_FILES = ("gbidi3/executor.py", "gbidi3/source.py", "gbidi3/trusted.py", "gbidi3/validate.py", "gbidi3/ir.py", "gbidi3/identity.py", "gbidi3/planner.py", "gbidi3/orders.py", "gbidi3/demand.py", "gbidi3/clock.py", "gbidi3/memory.py", "gbidi3/cell.py", "adp/source.py", "adp/publish.py", "adp/checker.py", "ext/uai.py")   # every module that shapes the executed program or its publication
EXECUTION_FIELDS = ("protocol", "arm", "budget_s", "config_sha256", "rules", "route", "attempt_id", "implementation")
IMPL_NATIVE_FIELDS = ("kind", "binary_sha256", "source_sha256", "flags_sha256", "python_sources_sha256")
IMPL_PYTHON_FIELDS = ("kind", "python_sources_sha256")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def sha_bytes(b):
    return hashlib.sha256(b).hexdigest()


def sha_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for ch in iter(lambda: f.read(1 << 20), b""):
            h.update(ch)
    return h.hexdigest()


def config_sha256(cfg):
    """sorted-JSON hash of the FULL cell configuration (every non-code execution field); budget_s is a separate field"""
    return sha_bytes(json.dumps({k: v for k, v in cfg.items() if k != "budget_s"}, sort_keys=True, default=str).encode())


def python_sources_sha256(root=HERE):
    return {f: sha_file(os.path.join(root, f)) for f in PYTHON_IMPL_FILES if os.path.exists(os.path.join(root, f))}


def native_implementation(build_record):
    b = build_record
    return {"kind": "native_kernel", "binary_sha256": b.get("binary_sha256"), "source_sha256": b.get("source_sha256"), "flags_sha256": sha_bytes(json.dumps(b.get("flags"), sort_keys=True).encode()), "python_sources_sha256": python_sources_sha256()}


def python_implementation():
    return {"kind": "python_exact", "python_sources_sha256": python_sources_sha256()}


def execution_identity(arm, budget_s, cfg, route, attempt_id, build_record=None):
    impl = native_implementation(build_record) if route in NATIVE_ROUTES else python_implementation()
    return {"protocol": PROTOCOL, "arm": arm, "budget_s": float(budget_s), "config_sha256": config_sha256(cfg), "rules": list(cfg.get("rules", ["exclude", "constants", "separate", "alias", "quotient"])), "route": route, "attempt_id": attempt_id, "implementation": impl}


def check_execution(got, expected, require_route=None):
    """positive equality on every EXECUTION field and every implementation field of the route; returns a list of reasons (empty = bound)"""
    reasons = []
    if not isinstance(got, dict):
        return ["execution identity missing"]
    for k in EXECUTION_FIELDS:
        if k not in got or k not in expected:
            reasons.append("execution field %s missing" % k)
        elif k != "implementation" and got[k] != expected[k]:
            reasons.append("execution field %s differs" % k)
    route = got.get("route")
    if require_route is not None and route != require_route:
        reasons.append("route %r is not the required %r" % (route, require_route))
    gi = got.get("implementation"); ei = expected.get("implementation")
    if not isinstance(gi, dict) or not isinstance(ei, dict):
        reasons.append("implementation binding missing"); return reasons
    fields = IMPL_NATIVE_FIELDS if route in NATIVE_ROUTES else (IMPL_PYTHON_FIELDS if route in PYTHON_ROUTES else None)
    if fields is None:
        reasons.append("unknown route %r" % route); return reasons
    for k in fields:
        if k not in gi or k not in ei:
            reasons.append("implementation field %s missing" % k)
        elif gi[k] != ei[k]:
            reasons.append("implementation field %s differs" % k)
    return reasons


def check_task(got, expected, fields):
    if not isinstance(got, dict):
        return ["task binding missing"]
    return ["task field %s missing or differs" % k for k in fields if k not in got or k not in expected or got[k] != expected[k]]
