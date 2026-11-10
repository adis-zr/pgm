"""Closeout extraction of GENERAL_BIDI_COMPLETE_V3 through the ONE strict reconciler (gbidi3.reconcile) and the ONE nonnested accounting rule
(gbidi3.pilot.charged). Used by the harness controls at the present stop point; the full report / scoring / mechanisms generator belongs to the reviewed
round and is prepared in gbidi3_closeout.plan (schema only, no outcomes)."""
from __future__ import annotations
import os, json
from gbidi3 import reconcile as RC, pilot as PI


def median(xs):
    xs = sorted(xs)
    if not xs:
        return None
    n = len(xs); return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def cells_ledger(D, man):
    idx = RC.ledger_index(D); return [RC.reconcile(D, man, c, idx) for c in man["cells"]]


def budget(D, man, cells):
    total, by, unresolved, extra = PI.charged(D)
    comp = "every start has exactly one receipt; no unresolved cleanup; nonnested (children + parent-only remainders)" if not unresolved and not extra["duplicate_receipts"] else "QUALIFIED"
    return {"total_charged_s": total, "by_scope": by, "unresolved": [u.get("job") for u in unresolved], "duplicate_receipts": extra["duplicate_receipts"], "outer_attempts": extra["outer_attempts"], "ceiling_s": man.get("ceiling_s"), "compliance": comp, "rule": "children + measured nonnegative parent-only remainder (gbidi3.pilot.charged)"}
