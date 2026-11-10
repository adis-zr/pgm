"""Clocks and metadata caps of GENERAL_BIDI_COMPLETE_V3 (brief §12): ONE launch-relative hard deadline shared by every layer; ONE optional
allowance min(1 s, 0.05 * budget) for optional discovery (views, demand refinement, fusion pricing, optional conditioning candidates), never renewed;
one shared cap of 3,000,000 metadata updates for the order heuristics; 1,000,000 optional row inspections; at most 3 monotone demand passes;
POLL_UNITS = 4096 primitive units between deadline checks in every planning / parsing / validation loop."""
from __future__ import annotations
import time

METADATA_UPDATE_CAP = 3_000_000
ROW_INSPECTION_CAP = 1_000_000
MAX_DEMAND_PASSES = 3
POLL_UNITS = 4096
TWO_AXIS_JOINT_MAX = 4096
BLOCK_ENTRIES = 1024


class PlanStop(Exception):
    def __init__(self, kind, reason):
        super().__init__("%s: %s" % (kind, reason)); self.kind = kind; self.reason = reason


class Clock:
    """hard_deadline: the cell's absolute monotonic deadline (never reset). optional_deadline: set once when optional discovery begins."""
    __slots__ = ("hard_deadline", "optional_deadline", "optional_allowance_s", "optional_started", "expired", "ticks", "rows", "row_cap", "meta", "meta_cap")

    def __init__(self, hard_deadline, budget_s):
        self.hard_deadline = hard_deadline; self.optional_allowance_s = min(1.0, 0.05 * float(budget_s)); self.optional_deadline = None; self.optional_started = None; self.expired = False
        self.ticks = 0; self.rows = 0; self.row_cap = ROW_INSPECTION_CAP; self.meta = 0; self.meta_cap = METADATA_UPDATE_CAP

    def begin_optional(self):
        if self.optional_started is None:
            self.optional_started = time.monotonic(); self.optional_deadline = self.optional_started + self.optional_allowance_s
            if self.hard_deadline is not None:
                self.optional_deadline = min(self.optional_deadline, self.hard_deadline)

    def check_hard(self):
        if self.hard_deadline is not None and time.monotonic() > self.hard_deadline:
            raise PlanStop("CELL_DEADLINE", "the cell deadline passed during planning")

    def check_optional(self):
        self.check_hard()
        if self.optional_deadline is None:
            self.begin_optional()
        if time.monotonic() > self.optional_deadline:
            self.expired = True; raise PlanStop("DISCOVERY_WALL", "the optional discovery allowance is exhausted")

    def tick(self, n=1, optional=False):
        self.ticks += n
        if self.ticks % POLL_UNITS < n:
            (self.check_optional if optional else self.check_hard)()

    def spend_rows(self, n):
        """optional row inspections (views / supports / demand)"""
        self.rows += n
        if self.rows > self.row_cap:
            raise PlanStop("ROW_CAP", "optional row inspection cap exhausted")
        self.tick(n, optional=True)

    def spend_meta(self, n=1):
        """order-heuristic metadata updates (mandatory work: hard deadline only, shared cap)"""
        self.meta += n
        if self.meta > self.meta_cap:
            raise PlanStop("METADATA_CAP", "the shared metadata update cap is exhausted")
        self.tick(n, optional=False)

    def remaining_rows(self):
        return max(0, self.row_cap - self.rows)

    def record(self):
        return {"optional_allowance_s": self.optional_allowance_s, "optional_started": self.optional_started is not None, "optional_expired": self.expired, "ticks": self.ticks, "rows_inspected": self.rows, "row_cap": self.row_cap, "metadata_updates": self.meta, "metadata_cap": self.meta_cap}
