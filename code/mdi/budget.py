"""One shared budget and deadline object (contract §G, §F.7).

A SINGLE monotonic deadline and shared counters across discovery, local
construction, checking, fitting, profiling and execution. A legitimate resource
stop is an outcome, never permission to extend a cap.

Previously each phase built its own deadline from its own start time, caps were
silently enlarged (the 4096 region-assignment cap was multiplied by 64 in two
places), and counters reset at the wrong scope.
"""
from __future__ import annotations
import sys, time, threading
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr


class BudgetExceeded(Exception):
    """A declared budget was reached. An OUTCOME, not a reason to raise a cap."""

    def __init__(self, kind, used, limit, where=""):
        self.kind, self.used, self.limit, self.where = kind, used, limit, where
        super().__init__("%s budget exhausted: used %s of %s%s"
                         % (kind, used, limit, (" at " + where) if where else ""))


class Budget:
    """Shared across every phase of one invocation.

    `wall_s` is a single monotonic deadline measured from construction. Counter
    limits are hard: `charge` raises rather than clamping, so no caller can
    quietly proceed past one.
    """

    def __init__(self, wall_s, limits=None, rss_fn=None, rss_limit=None):
        self.t0 = time.monotonic()
        self.wall_s = float(wall_s)
        self.limits = dict(limits or {})
        self.used = {}
        self.rss_fn = rss_fn
        self.rss_limit = rss_limit
        self.peak_rss = 0
        self._lock = threading.Lock()
        self.stops = []
        self.phase = "init"
        self._checks = 0

    # ---- time ----
    def elapsed(self):
        return time.monotonic() - self.t0

    def remaining(self):
        """Seconds left. May be NEGATIVE; callers must not clamp it to a
        positive value and keep working."""
        return self.wall_s - self.elapsed()

    def check(self, where=""):
        """The single deadline and memory test. Call inside interior loops."""
        self._checks += 1
        el = self.elapsed()
        if el > self.wall_s:
            self.stops.append({"kind": "wall", "used": el,
                               "limit": self.wall_s, "where": where or self.phase})
            raise BudgetExceeded("wall", round(el, 3), self.wall_s,
                                 where or self.phase)
        if self.rss_fn is not None and self.rss_limit:
            cur = self.rss_fn()
            if cur > self.peak_rss:
                self.peak_rss = cur
            if cur > self.rss_limit:
                self.stops.append({"kind": "rss", "used": cur,
                                   "limit": self.rss_limit,
                                   "where": where or self.phase})
                raise BudgetExceeded("rss", cur, self.rss_limit,
                                     where or self.phase)

    # ---- counters ----
    def charge(self, name, amount=1, where=""):
        """Add to a shared counter and enforce its limit if one is declared."""
        with self._lock:
            self.used[name] = self.used.get(name, 0) + amount
            cur = self.used[name]
        lim = self.limits.get(name)
        if lim is not None and cur > lim:
            self.stops.append({"kind": name, "used": cur, "limit": lim,
                               "where": where or self.phase})
            raise BudgetExceeded(name, cur, lim, where or self.phase)
        return cur

    def would_exceed(self, name, amount):
        """Check BEFORE allocating, as contract F.7 requires."""
        lim = self.limits.get(name)
        if lim is None:
            return False
        return self.used.get(name, 0) + amount > lim

    def require(self, name, amount, where=""):
        """Refuse an allocation that would breach a cap, without performing it."""
        if self.would_exceed(name, amount):
            lim = self.limits.get(name)
            self.stops.append({"kind": name, "used": self.used.get(name, 0) + amount,
                               "limit": lim, "where": where or self.phase})
            raise BudgetExceeded(name, self.used.get(name, 0) + amount, lim,
                                 where or self.phase)
        return True

    def enter(self, phase):
        """Begin a stage. Every stage boundary is a hard enforcement point:
        the shared deadline and RSS cap are tested BEFORE the stage runs, so a
        run that is already over budget cannot start more work. Previously
        `check` existed but was never called from the pipeline, so a mocked
        2 GiB RSS under a 1 GiB cap certified with ZERO shared-budget checks,
        and an 80 ms checker under a 20 ms deadline certified with a negative
        remaining time."""
        self._enter_raw(phase)
        self.check("enter:" + phase)

    def _enter_raw(self, phase):
        self.phase = phase
        return self

    def deadline_fn(self, where=""):
        """A zero-argument callable for the inner loops."""
        def _dl():
            self.check(where)
        return _dl

    def report(self):
        return {"wall_s": self.wall_s, "elapsed_s": round(self.elapsed(), 3),
                "remaining_s": round(self.remaining(), 3),
                "used": dict(self.used), "limits": dict(self.limits),
                "peak_rss": self.peak_rss, "rss_limit": self.rss_limit,
                "stops": list(self.stops), "checks": self._checks,
                "note": "one monotonic deadline and shared counters across "
                        "every phase; a stop is an outcome, never a reason to "
                        "raise a cap"}


# ---------------- per-entry conversion cache (contract §G) ----------------

class ConversionCache:
    """Cache each exact factor entry's numerical enclosure.

    Keyed by (precision, rounding, emin, emax, exact value), so a changed
    precision or exponent range cannot reuse a stale conversion. Producer and
    checker build SEPARATE caches; the conversion error stays attached to each
    mathematical use, so sharing a cache across arms is not permitted.
    """

    def __init__(self, ctx, label=""):
        self.ctx = ctx
        self.label = label
        self.key = (ctx.p, ctx.emin, ctx.emax)
        self._down = {}
        self._up = {}
        self.hits = 0
        self.misses = 0

    def down(self, q: Fr):
        try:
            v = self._down[q]
            self.hits += 1
            return v
        except KeyError:
            self.misses += 1
            v = self.ctx.down(q)
            self._down[q] = v
            return v

    def up(self, q: Fr):
        try:
            v = self._up[q]
            self.hits += 1
            return v
        except KeyError:
            self.misses += 1
            v = self.ctx.up(q)
            self._up[q] = v
            return v

    def stats(self):
        tot = self.hits + self.misses
        return {"label": self.label, "context": self.key,
                "distinct_down": len(self._down), "distinct_up": len(self._up),
                "hits": self.hits, "misses": self.misses,
                "hit_rate": (self.hits / tot) if tot else 0.0}
