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


# the process-wide default clock: the lifecycle controls inject a fake clock
# here so parse delays, terminal-write delays and phase timeouts are
# deterministic; production never touches it
DEFAULT_CLOCK = [time.monotonic]


class Budget:
    """Shared across every phase of one invocation.

    `wall_s` is a single monotonic deadline measured from construction. Counter
    limits are hard: `charge` raises rather than clamping, so no caller can
    quietly proceed past one.
    """

    # phases that share one cumulative time allowance: discovery and the
    # construction work repeated while persisting / repricing count against
    # the SAME 30 s; independent local certificate checking has its own 30 s
    PHASE_GROUPS = {"discover": "construction", "persist": "construction",
                    "check_local": "check_local"}
    PHASE_LIMITS = {"construction": 30.0, "check_local": 30.0}
    PHASE_LEAVE_ENFORCED = {"check_local"}

    def __init__(self, wall_s, limits=None, rss_fn=None, rss_limit=None, phase_limits=None,
                 clock=None):
        self.progress = None          # progress(phase, info), set by the owner
        # the clock is INJECTABLE so the lifecycle controls (parse delay,
        # terminal-write delay, local-proof and numerical-check timeouts) run
        # deterministically; production uses the monotonic clock
        self._clock = clock or DEFAULT_CLOCK[0]
        self.t0 = self._clock()
        self.wall_s = float(wall_s)
        self.limits = dict(limits or {})
        self.phase_limits = dict(self.PHASE_LIMITS if phase_limits is None else phase_limits)
        self.phase_time = {}          # group -> seconds accumulated in completed phases
        self.phase_t0 = self.t0
        self.used = {}
        self.rss_fn = rss_fn
        self.rss_limit = rss_limit
        self.peak_rss = 0
        self._lock = threading.Lock()
        self.stops = []
        self.phase = "init"
        self.phases = []              # every phase entered, in order (reviewable)
        self._checks = 0

    # ---- time ----
    def elapsed(self):
        return self._clock() - self.t0

    def remaining(self):
        """Seconds left. May be NEGATIVE; callers must not clamp it to a
        positive value and keep working."""
        return self.wall_s - self.elapsed()

    def check(self, where=""):
        """The single deadline and memory test. Call inside interior loops."""
        self._checks += 1
        el = self.elapsed()
        if self.progress is not None and (self._checks & 0x3F) == 0:
            # durable progress from INSIDE long loops (§14): the caller's
            # hook throttles its own emission
            self.progress(where or self.phase,
                          "checks=%d used=%s" % (self._checks,
                                                 {k: v for k, v in self.used.items()}))
        if el > self.wall_s:
            self.stops.append({"kind": "wall", "used": el,
                               "limit": self.wall_s, "where": where or self.phase})
            raise BudgetExceeded("wall", round(el, 3), self.wall_s,
                                 where or self.phase)
        grp = self.PHASE_GROUPS.get(self.phase)
        if grp is not None and grp in self.phase_limits:
            pused = self.phase_time.get(grp, 0.0) + (self._clock() - self.phase_t0)
            if pused > self.phase_limits[grp]:
                self.stops.append({"kind": "phase:" + grp, "used": round(pused, 3),
                                   "limit": self.phase_limits[grp], "where": where or self.phase})
                raise BudgetExceeded("phase:" + grp, round(pused, 3), self.phase_limits[grp],
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
        # LEAVING the local-check phase is an enforcement point for its
        # allowance: a local proof that overran its 30 s stops here, before
        # the global reference contraction can start. (The construction
        # allowance is different: its exhaustion ENDS discovery and the
        # completed plans and the identity fallback proceed; it is tested
        # inside the construction loops, never on leaving.)
        if self.PHASE_GROUPS.get(self.phase) in self.PHASE_LEAVE_ENFORCED:
            self.check("leave:" + str(self.phase))
        self._enter_raw(phase)
        self.phases.append(str(phase))
        self.check("enter:" + phase)

    def _enter_raw(self, phase):
        now = self._clock()
        grp = self.PHASE_GROUPS.get(self.phase)
        if grp is not None:
            self.phase_time[grp] = self.phase_time.get(grp, 0.0) + (now - self.phase_t0)
        self.phase = phase
        self.phase_t0 = now
        return self

    def phase_used(self, group):
        """Seconds consumed by a phase group so far (completed + current)."""
        cur = (self._clock() - self.phase_t0) if self.PHASE_GROUPS.get(self.phase) == group else 0.0
        return self.phase_time.get(group, 0.0) + cur

    def phase_exhausted(self, group):
        lim = self.phase_limits.get(group)
        return lim is not None and self.phase_used(group) > lim

    def deadline_fn(self, where=""):
        """A zero-argument callable for the inner loops."""
        def _dl():
            self.check(where)
        return _dl

    def report(self):
        return {"wall_s": self.wall_s, "elapsed_s": round(self.elapsed(), 3),
                "remaining_s": round(self.remaining(), 3),
                "used": dict(self.used), "limits": dict(self.limits),
                "phases": list(self.phases),
                "phase_limits": dict(self.phase_limits),
                "phase_used_s": {g: round(self.phase_used(g), 3) for g in self.phase_limits},
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
