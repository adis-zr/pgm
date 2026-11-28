"""BOUNDED FAILURE DIAGNOSTICS that survive both graceful deadlines and hard kills (overseer prompt of 17 Nov 2026, section 2).

A worker creates ONE Diagnostics object BEFORE expensive parsing and keeps it current at phase transitions and at bounded periodic consistent points (controller
service points, compiler step boundaries, adaptive-loop turns). Every checkpoint is written ATOMICALLY (tmp + os.replace) to a sidecar OUTSIDE the worker's
publication file, so a SIGKILLed attempt still exposes its latest valid checkpoint with an explicit freshness limit (`freshness.elapsed_s_at_write`). The compiler
journal is persisted INCREMENTALLY (one JSON line per committed record, fsync'ed at every checkpoint); a checkpoint refers only to the durable prefix it fsync'ed
(`compiler.journal_durable_lines`). Summaries are bounded and state their coverage; a missing measurement is None with a `missing` label, never zero.

Telemetry is diagnostic EVIDENCE: it is never a certificate and can never turn a late or incomplete result into a publication. Its own cost (time inside writes) is
measured and reported (`overhead_s`) and is NOT part of the Work ledger (the Work unit = table entry read / rational op / point evaluation / cell op is unchanged)."""
import json, os, time

DIAG_VERSION = 'cqr-diag-v1.1 (2026-11-17, structured review CQR-S1-06: per-section update ages; every terminal write refreshes the cheap maintained state through a registered callback, independent of the periodic write clock; section refresh clocks separate from the checkpoint clock; v1: atomic sidecar checkpoints; incremental fsync\'ed journal; bounded summaries with declared coverage; overhead measured)'
RING = 64              # bounded event ring
TOPK = 8               # limiting coordinates retained per enclosure summary


def _atomic_write(path, obj):
    tmp = path + '.tmp'
    with open(tmp, 'w') as fh: json.dump(obj, fh, default=str); fh.flush(); os.fsync(fh.fileno())
    os.replace(tmp, path)


class NullDiag:
    """the no-op diagnostics object used when no sidecar path is given (in-process qualification calls); every method is a no-op with the same signature"""
    overhead_s = 0.0; path = None; journal_path = None
    def phase(self, name): pass
    def event(self, kind, **kw): pass
    def set(self, section, **kw): pass
    def service_tick(self, op, work_ref=None, work_opt=None, rss=None): pass
    def enter(self, op): pass
    def leave(self, op): pass
    def reference(self, ref): pass
    def compiler(self, C=None, log=None): pass
    def frontier(self, fr, det=None, work_now=None, queries=None): pass
    def streams(self, ratio=None, epochs=None, note=None): pass
    def planner(self, candidate=None, decision=None): pass
    def cost(self, key, seconds): pass
    def journal(self, rec): pass
    def maybe_write(self, reason): pass
    def write(self, reason): pass
    def due(self): return False
    def section_due(self, section): return False
    def register_refresh(self, fn): pass
    finalized = False
    def final(self, status, outcome, reason=None): return None
    def summary(self): return None


class Diagnostics:
    def __init__(self, path, identity, t0, deadline_abs, min_interval_s=0.25, journal_path=None):
        self.path = path; self.t0 = t0; self.deadline = deadline_abs; self.min_interval = min_interval_s; self.overhead_s = 0.0; self.n_writes = 0; self.last_write_elapsed = None
        self._updated = {}; self._refresh = None; self._section_clock = {}
        self.journal_path = journal_path or (path[:-5] + '.journal.jsonl' if path.endswith('.json') else path + '.journal.jsonl'); self._jfh = None; self._jlines = 0; self._jdurable = 0
        self.state = dict(schema=DIAG_VERSION, status='RUNNING', identity=identity, sidecar_path=path, journal_path=self.journal_path, phase='start', phase_started_elapsed_s=0.0, phase_times_s={}, elapsed_s=0.0,
                          deadline=dict(budget_s=None, remaining_s=None, expired=False), service=dict(controller_calls=0, last_service_elapsed_s=None, reference_service_calls=0, in_flight=None, last_completed=None, note='in_flight = the operation entered and not yet left at the last checkpoint (an indivisible primitive inside it is not observable)'),
                          memory=dict(rss_bytes=None, missing='rss not sampled yet'), work=dict(reference=None, optional=None, structural=None, missing='no ledger snapshot yet'),
                          reference=dict(assignments_done=None, assignments_total=None, progress=None, done=None, missing='reference not constructed yet'),
                          compiler=dict(quota=None, steps=[], commits=0, journal_lines=0, journal_durable_lines=0, last_commit_measure=None, bias=None, declines=[], interrupted=None, failed=None, coverage='every operator step outcome (op, outcome, work, reason) as the driver records it; declines keep their typed reason'),
                          frontier=dict(missing='no frontier yet'), streams=dict(ratio=None, signed_epochs=[], notes=[], coverage='launch / stop / retire reasons; counts'),
                          planner=dict(candidates=[], decisions=[], coverage='every structural route considered: applicability, estimate, allocation, outcome'),
                          costs_s=dict(parse=None, reference_init=None, compile=None, structural=None, frontier_init=None, adaptive=None, publication=None, checking=None, diagnostics=0.0, coverage='phase wall times from phase transitions; diagnostics = time inside checkpoint writes'),
                          events=[], checkpoints=0, freshness=dict(elapsed_s_at_write=None, section_ages_s={}, note='the sidecar is as fresh as its last checkpoint; a hard kill leaves this record with elapsed_s_at_write < the kill time; section_ages_s = elapsed since each section was last UPDATED (a fresh checkpoint can carry an older section: the age says so)'),
                          enumerator=dict(note='reference assignments are counted separately from Work units'))
        self.write('start')

    # ---- bounded updates
    def phase(self, name):
        now = time.monotonic() - self.t0; prev = self.state['phase']; self.state['phase_times_s'][prev] = round(self.state['phase_times_s'].get(prev, 0.0) + (now - self.state['phase_started_elapsed_s']), 6)
        self.state['phase'] = name; self.state['phase_started_elapsed_s'] = round(now, 6); self.write('phase:' + name)
    def event(self, kind, **kw):
        ev = dict(kind=kind, elapsed_s=round(time.monotonic() - self.t0, 6), **kw); self.state['events'].append(ev)
        if len(self.state['events']) > RING: self.state['events'] = self.state['events'][-RING:]
    def _touch(self, section): self._updated[section] = round(time.monotonic() - self.t0, 6)
    def set(self, section, **kw):
        d = self.state.setdefault(section, {}); d.update(kw); d.pop('missing', None); self._touch(section)
    def section_due(self, section):
        """True when `section` has not been refreshed for min_interval (its OWN clock; a service checkpoint never postpones it)"""
        now = time.monotonic() - self.t0; last = self._section_clock.get(section)
        if last is None or now - last >= self.min_interval: self._section_clock[section] = now; return True
        return False
    def register_refresh(self, fn):
        """the solver registers a cheap callback that pushes every maintained counter / ledger / stream count into the state; `final` calls it before the terminal write"""
        self._refresh = fn
    def enter(self, op):
        """OPERATION ENTRY (CQR-S1-05/06 observability): records the operation now in flight and its entry time; a checkpoint written while it runs shows what was running and for how long
        (the sidecar never claims the operation finished). Written at the normal cadence (a long operation's entry is captured by the next service checkpoint or by this call when due)."""
        s = self.state['service']; s['in_flight'] = dict(op=op, entered_elapsed_s=round(time.monotonic() - self.t0, 6)); self._touch('service'); self.maybe_write('enter:' + op)
    def leave(self, op):
        s = self.state['service']; f = s.get('in_flight')
        if f and f.get('op') == op: s['last_completed'] = dict(op=op, wall_s=round(time.monotonic() - self.t0 - f['entered_elapsed_s'], 6)); s['in_flight'] = None; self._touch('service')
    def service_tick(self, op, work_ref=None, work_opt=None, rss=None):
        s = self.state['service']; s['controller_calls'] += 1; s['last_service_elapsed_s'] = round(time.monotonic() - self.t0, 6); s['last_op'] = op
        if work_ref is not None: self.state['work']['reference'] = work_ref.snapshot()
        if work_opt is not None: self.state['work']['optional'] = work_opt.snapshot()
        if work_ref is not None or work_opt is not None: self.state['work'].pop('missing', None); self._touch('work')
        if rss is not None: self.state['memory'] = dict(rss_bytes=rss); self._touch('memory')
        self._touch('service'); self.maybe_write('service')
    def reference(self, ref):
        self.state['reference'] = dict(assignments_done=ref.idx, assignments_total=ref.total, progress=(ref.idx / ref.total if ref.total else 1.0), done=ref.done); self._touch('reference')
    def compiler(self, C=None, log=None):
        c = self.state['compiler']
        if log is not None:
            c['quota'] = log.get('quota'); c['steps'] = [dict(op=s.get('op'), outcome=s.get('outcome'), work=s.get('work'), commits=s.get('commits'), reason=(s.get('reason') or s.get('error') or s.get('kind'))) for s in (log.get('steps') or [])]
            c['interrupted'] = log.get('interrupted'); c['failed'] = log.get('failed'); c['declines'] = [dict(op=s['op'], reason=str(s.get('reason'))[:160]) for s in (log.get('steps') or []) if s.get('outcome') == 'declined'][-RING:]
        if C is not None:
            c['commits'] = C.commits; c['journal_lines'] = self._jlines; c['journal_durable_lines'] = self._jdurable; c['last_commit_measure'] = C.measure(); c['bias'] = [str(b) for b in C.bias]
            c['scratch_note'] = 'in-progress operator scratch is never part of the committed state (builders freeze into a new commit or are discarded)'
        self._touch('compiler')
    def frontier(self, fr, det=None, work_now=None, queries=None):
        f = dict(open_cells=len(fr.open), resolved_cells=fr.resolved_cells, splits=fr.splits, closures=fr.closures, max_depth=max((c.depth for c in fr.open.values()), default=0), n=fr.n, resolved_mass=str(fr.resolved_mass), coverage='counts over every open cell; enclosure summary = the LAST computed deterministic bounds (not recomputed here)')
        if det is not None:
            widths = []
            for j, b in enumerate(det):
                if b[0] == 'UNDEFINED': widths.append((None, j, 'UNDEFINED')); continue
                widths.append((float(b[1] - b[0]), j, None))
            defined = [w for w in widths if w[0] is not None]; defined.sort(reverse=True)
            f['last_enclosure'] = dict(elapsed_s=round(time.monotonic() - self.t0, 6), work_optional_at=work_now, queries=len(det), undefined=sum(1 for w in widths if w[2] == 'UNDEFINED'), max_width=(defined[0][0] if defined else None),
                                       widest_coordinates=[dict(query=j, width=w, name=(queries[j]['name'] if queries and j < len(queries) else None)) for w, j, _ in defined[:TOPK]], coverage='the %d widest of %d coordinates' % (min(TOPK, len(defined)), len(defined)))
        else: f['last_enclosure'] = self.state.get('frontier', {}).get('last_enclosure')
        self.state['frontier'] = f; self._touch('frontier')
    def streams(self, ratio=None, epochs=None, note=None):
        s = self.state['streams']
        if ratio is not None: s['ratio'] = dict(draws=ratio.t, stopped=ratio.stopped, alpha=str(ratio.alpha), U_star=str(ratio.U_star))
        if epochs is not None: s['signed_epochs'] = [dict(epoch=e.epoch, draws=e.t, retired=e.retired, delta_e=str(e.delta_e) if hasattr(e, 'delta_e') else None) for e in epochs][-RING:]
        if note: s['notes'].append(dict(elapsed_s=round(time.monotonic() - self.t0, 6), note=str(note)[:200])); s['notes'] = s['notes'][-RING:]
        self._touch('streams')
    def planner(self, candidate=None, decision=None):
        p = self.state['planner']
        if candidate is not None: p['candidates'].append(candidate)
        if decision is not None: p['decisions'].append(dict(elapsed_s=round(time.monotonic() - self.t0, 6), **decision))
        self._touch('planner')
    def cost(self, key, seconds): self.state['costs_s'][key] = round((self.state['costs_s'].get(key) or 0.0) + seconds, 6)

    # ---- journal (incremental, durable prefix)
    def journal(self, rec):
        if self._jfh is None: self._jfh = open(self.journal_path, 'a')
        self._jfh.write(json.dumps(rec, default=str) + '\n'); self._jfh.flush(); self._jlines += 1
    def _journal_sync(self):
        if self._jfh is not None: os.fsync(self._jfh.fileno()); self._jdurable = self._jlines

    # ---- checkpoint writes (atomic)
    def due(self):
        """True when a periodic checkpoint is due (the caller refreshes the bounded summaries first, then calls write)"""
        now = time.monotonic() - self.t0; return self.last_write_elapsed is None or now - self.last_write_elapsed >= self.min_interval
    def maybe_write(self, reason):
        now = time.monotonic() - self.t0
        if self.last_write_elapsed is None or now - self.last_write_elapsed >= self.min_interval: self.write(reason)
    def write(self, reason):
        t = time.monotonic(); now = t - self.t0
        self.state['elapsed_s'] = round(now, 6); self.state['last_checkpoint_reason'] = reason; self.state['checkpoints'] += 1
        if self.deadline is not None: self.state['deadline'] = dict(budget_s=self.state['deadline'].get('budget_s'), remaining_s=round(self.deadline - t, 6), expired=(t >= self.deadline))
        self._journal_sync(); self.state['compiler']['journal_lines'] = self._jlines; self.state['compiler']['journal_durable_lines'] = self._jdurable
        self.state['freshness']['elapsed_s_at_write'] = round(now, 6); self.state['freshness']['section_ages_s'] = {k: round(now - v, 6) for k, v in sorted(self._updated.items())}; self.state['overhead_s'] = round(self.overhead_s, 6); self.state['costs_s']['diagnostics'] = round(self.overhead_s, 6)
        try: _atomic_write(self.path, self.state)
        except OSError as ex: self.state['write_error'] = str(ex)[:120]
        dt = time.monotonic() - t; self.overhead_s += dt; self.n_writes += 1; self.last_write_elapsed = now
    finalized = False
    def final(self, status, outcome, reason=None):
        """the LAST checkpoint, assembled from already-maintained state (no fresh bounds, no proof completion, no unbounded dump); idempotent (the first final wins)"""
        if self.finalized: return self.summary()
        self.finalized = True
        if self._refresh is not None:
            t = time.monotonic()
            try: self._refresh()                      # cheap maintained state only (ledgers, counts, stream draws, reference progress, frontier counts); never a fresh bound or proof
            except Exception as ex: self.state['refresh_error'] = str(ex)[:120]
            self.overhead_s += time.monotonic() - t
        self.state['status'] = status; self.state['outcome'] = outcome; self.state['final_reason'] = (str(reason)[:300] if reason else None); self.write('final'); return self.summary()
    def summary(self):
        s = self.state; return dict(schema=s['schema'], sidecar=self.path, journal=self.journal_path, checkpoints=s['checkpoints'], overhead_s=round(self.overhead_s, 6), phase=s['phase'], phase_times_s=s['phase_times_s'], last_enclosure=(s.get('frontier') or {}).get('last_enclosure'), planner_decisions=s['planner']['decisions'][-8:], reference=s['reference'], work=s['work'])
