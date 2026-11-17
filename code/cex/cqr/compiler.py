"""CQR REDUCTION COMPILER (manuscript §3; supporting notes query_structure_algorithm.txt, reduction_algorithms.txt). Transactional: every operator PROPOSES from
source data, CONSTRUCTS a candidate on NEW objects, VERIFIES its certificate against the current compiled model with exact arithmetic (the `verify_*` functions below are
the same ones the independent checker calls on the recorded chain), then COMMITS atomically. Finite work quota (policy); canonical order; no unchanged proposal is retried.

ATOMIC LOCAL COMMITS (second review, R1/R2): the compiled state (cards, views, queries, decoder, bias, scalars, constant queries, witness) is a sequence of IMMUTABLE
snapshots; committed View / query / decoder objects are never mutated in place -- every change builds new objects and `Compiled.commit` swaps the whole state in one step
while appending ONE replayable certificate record (kind 'commit') to the journal `C.certs`. A decline is a journal record of kind 'decline' (no state change). The service /
quota / deadline hook `tick` may raise inside any read-only scan or candidate construction (state unchanged) and never between the swap and its record. An optional
FAILURE anywhere therefore leaves the state at the LAST COMMIT (asserted; `_restore_state` is a belt-and-braces safety net), and the checker replays EXACTLY the
recorded commits (`apply_commit` after `verify_commit` on the pre-commit model) -- never 'the first tick of the named operator', never a whole operator per fragment.
One representation for every operator outcome (log['steps'][i]['outcome']): committed | no_change | declined | quota | interrupted(deadline | reference_done | cancelled) |
failed | disabled | skipped, each with the number of commits it left in the journal.

SERVICE GRANULARITY (R3; fourth review CQR-R3-04): every bounded scan (slices, axis rebuilds, class averaging, leaf integration, signatures, kappa products, surrogate
ratios and construction, symmetry checks, affine rows, influence pair scans, concentration argmax / witness weights, evidence restriction) posts its units through a
_Meter bound to the operator's _Ticker; the charged-since-service counter lives on the compiled state, the meter compares its pending count with the REMAINING
allowance after every indivisible step (<= POLICY['max_step_charge'] = 2 units) and posts when reached, so leftovers carry across helpers and operators and `tick`
is called at most TICK_ENTRIES + max_step_charge - 1 = 1,025 charged units apart (POLICY['service_gap_proof']); the declared max_irreducible_charge = 1,026 is a
valid upper bound. EXACTLY-ONCE ACCOUNTING (fifth review CQR-R4-01 / 02): a meter hands its pending count to the ledger BEFORE the service point runs and every metered
loop is a context manager that flushes its completed tail on every exit (serviced on a normal exit, charge-only while an exception propagates), so the ledger increment of a
loop equals its completed operations on every exit path, no stop triggers a second service call, and rollback restores model state only; work delegated by `commit` (witness
validation) runs under the compiled state's ACTIVE operator ticker (quota / deadline / service inherited; replay = the explicit quota-less context). An over-size raw post
is charged and then reported. EVERY TICK IS A CONTROLLER SERVICE (sixth review CQR-R5-02): `tick` invokes the controller hook before testing the operator quota, so a quota exit
never skips or resets a pending service; the controller's stops dominate; `max_service_gap` and `controller_calls` describe actual controller invocations. Charges are placed
AFTER the evaluation they count (CQR-R5-03), so the ledger equals the number of successful evaluations on every exit.

Operators (mandatory set A-E of the handoff):
  A  evidence restriction; checked support propagation (identically-zero incident slices remove states; empty domain / zero factor => ZERO_EVIDENCE); fixed-variable
     substitution; local leaf sum-out of a nonquery variable in exactly one factor; omission of a query-free component after a positivity proof (normalized tasks only);
     generic symmetry verifier with a bounded proposer (global binary complement; table-signature state swaps).
  B  exact proportional incident-slice quotient: classes = equal normalized slices in EVERY incident factor; multiplicity weights kappa / S; stochastic decoder; query
     tables averaged with kappa/S (both h and g of a ratio query).
  C  checked approximate quotient: common zero masks, canonical pivots, surrogate, ALL-entry ratio certificate l_a <= phi/phi~ <= u_a, R = prod u/l,
     beta = (R-1)/(R+3) spent from the bias allowance, then the exact quotient of the surrogate.
  D  local affine-support recognizer (|R| == 2^rank test), global GF(2) elimination (inconsistency => ZERO_EVIDENCE), compact linear-map views, query pullbacks
     (singletons become parities); applied ONCE, last, as the representation change.
  E  generic categorical influence (Dobrushin comparison; strictly positive tables required; zeros decline) with bounded deletion policy, and the concentration
     certificate (local ratio inequalities around a cheap proposed assignment) -> a direct certified answer with a proved bias.
Decoder (per ORIGINAL variable): fixed(state) | map(compiled var, {compiled state: [(orig state, weight)]}) stochastic | affine(c, z vars) | summed | omitted."""
import time
from fractions import Fraction as F
import sys as _sys; _sys.set_int_max_str_digits(0)
from itertools import product
from math import prod
from views import View, gf2_rank_basis, gf2_reduce, gf2_span
from task import Work
COMPILER_VERSION = 'cqr-compiler-v2.6 (2026-11-17: views own IMMUTABLE tuple storage borrowed without traversal by scope-only renumbering (no copy, no read); every builder freezes its metered scratch once; the approximate-quotient surrogate copy and the quotient unary rescale are charged; the concentration answer evaluations run under the operator ticker; the affine image copies a categorical-only table through the meter; max_service_gap covers the evidence-restriction phase; every producer table-read site declared in EVALUATION_SITES; atomic local commits, journal replay, exactly-once metered service points inside every scan, every tick a controller service, witness lifecycle under the operator quota)'
TICK_ENTRIES = 1024                   # service / quota / deadline check at most this many charged units apart inside every scan
POLICY = dict(
    compiler_version=COMPILER_VERSION,
    order=('evidence', 'support_fixpoint', 'fixed_substitution', 'leaf_sumout', 'component_omission', 'exact_quotient_pass', 'symmetry', 'approx_quotient', 'concentration', 'influence_deletion', 'affine'),
    quota_rule='discovery work quota D = max(50_000, 8 * (sum of source table entries + sum of query table entries)) work units; each operator stops at its share (the quota is tested inside every scan, so an operator overspends its share by at most max_irreducible_charge); the complete exact quotient pass gets its own share of size D',
    bias_reserve='DETERMINISTIC_EPS / PAC_EPS: at most epsilon/4 of every query allowance for compiler bias (manuscript §3.2); EXACT_RATIONAL: zero',
    symmetry_proposer='global binary complement; for each variable the state swap induced by sorting its unary signature (bounded: at most n + 1 candidates)',
    approx_quotient_order='variables in canonical order; states in canonical order; first representative group with a matching zero mask whose widened ratio certificate still fits the remaining bias allowance',
    influence_policy='all non-unary factors first; then greedy in order of decreasing table size (ties: factor index), each candidate accepted only if every query bias fits; Neumann T = 8',
    concentration_proposal='per variable the maximizer of the product of its unary factors (ties: first state); no coordinate ascent',
    well_founded='every committed operator strictly decreases (variables, total domain, factor+query entries) in lexicographic order, except affine (once, last)',
    transaction_rule='immutable committed objects; one atomic swap per local commit; one journal record per commit (replayable); declines recorded, never replayed; failure => state == last commit',
    service_rule='every scan posts its units through a _Ticker meter that checks the REMAINING allowance after every indivisible step (1 or 2 units) and services as soon as TICK_ENTRIES units have been charged since the previous service point; leftovers of one helper count toward the next; posted work is never refused (an over-size post is charged, then reported); EVERY tick invokes the controller BEFORE the operator quota is tested (controller stops dominate; a quota exit never skips or resets a pending service), so max_service_gap is the spacing of actual controller invocations',
    accounting_rule='EXACTLY ONCE: a meter transfers its pending count to the Work ledger before the service point runs (a stop raised there leaves nothing pending); every metered loop flushes its completed tail on every exit (serviced on a normal exit, charge-only while an exception propagates: the tail is below the allowance, so no service point is skipped and the typed stop is kept); rollback restores model state, never spent work; work delegated by commit (witness validation) runs under the ACTIVE operator ticker (its quota / deadline / service), the quota-less ticker is the explicit replay context',
    tick_entries=TICK_ENTRIES, max_step_charge=2, max_irreducible_charge=TICK_ENTRIES + 2,
    service_gap_proof='between two consecutive service points at most TICK_ENTRIES + max_step_charge - 1 = %d charged units (the counter of charged-since-service units lives on the compiled state, so leftovers carry across helpers and across operators): the meter compares its pending count with the remaining allowance after EVERY step of at most max_step_charge units and posts (servicing when the allowance is reached), so a post never exceeds the allowance by more than max_step_charge - 1; the declared bound max_irreducible_charge = %d is a valid (non-tight) upper bound; an operator quota is therefore overspent by at most that many units' % (TICK_ENTRIES + 1, TICK_ENTRIES + 2),
    evaluation_sites_rule='EVALUATION_SITES declares every producer function of this module that reads a table entry (View.at / View.at_i / view.values) together with the meter phase that charges the read; the qualification suite re-derives the set of such functions from the source and refuses a producer read site that is not declared (eighth review, CQR-R7-02 audit) AND verifies the declarations behaviourally with independent storage-level read counters (ninth review, CQR-R8-01: a "no read" declaration must show zero traversal and identical storage); view storage is an immutable tuple that the constructor borrows without traversal (views.VIEW_STORAGE_RULE), so delegated constructor work never copies; arithmetic on values already read (ratio / max / sum of read entries) is bounded by the charged reads and not separately charged unless listed as ratops',
    witness_rule='the positivity witness is model-dependent auxiliary state: every commit that changes cards, views or variable numbering must TRANSFORM it (support / fixed / leaf / omission / quotient / affine re-coordinate it; influence keeps it) or INVALIDATE it (None); the committed witness is validated on the resulting model (domain + strictly positive weight) and dropped with a recorded reason otherwise')


# every PRODUCER function of this module that reads a table entry (View.at / View.at_i / iteration or indexing of view.values) -> the meter / declared cost phase of the read.
# Verification-phase functions (the checker's re-derivations: verify_commit, _influence_recompute, apply_commit, replay_journal, verify_affine_record) charge lumps to the checker's
# Work ledger without service points (declared exclusion of the service theorem: verification). Audited by qualification group C27 against the source (eighth review, CQR-R7-02).
EVALUATION_SITES = dict(
    _witness_problem='evals meter of the ACTIVE operator ticker (commit-time witness validation; quota-less ticker in replay)',
    from_task='evidence-restriction phase: one entry per source / query table entry, serviced every TICK_ENTRIES (controller_calls_evidence; counted in max_service_gap)',
    _slice='entries meter of the caller\'s ticker (support / exact + approximate quotient / concentration ratio scans)',
    _replace_axis='entries meter (support apply / quotient build)', _average_axis='entries meter (quotient query averaging; the class sum split at the allowance)',
    _remove_var_from_scope_fixed='entries meter (fixed substitution)', _renumbered='NO READ: scopes renumbered; the new view BORROWS the old view\'s immutable value tuple (the identical object; VIEW_STORAGE_RULE) -- verified behaviourally by C28 (storage identity, zero traversal)',
    _fixed_apply='entries meter (the constant check reads one entry of each new scalar table)',
    _leaf_apply='entries meter (leaf sum-out)', _omission_proofs='entries meter (positivity scan, charged before the test) + evals meter (witness-restricted proof)',
    _quotient_build='ratops meter (kappa) + entries meter (unary rescale: one read of the new unary per class)', approx_quotient='entries meter (the surrogate starts from a charged copy of each incident table) + ratops meter (surrogate build)',
    verify_symmetry_action='entries meter (two lookups per compared assignment, charged after each)', _query_symmetric_constant='entries meter (two lookups per assignment)',
    _unary_product_argmax='entries meter (unary factor entries)', concentration='evals meter (witness weight) + _slice entries (ratio scans) + evals meter (answers at x*: CQR-R7-02)',
    influence_deletion='entries meter from the first read (applicability scan: CQR-R6-02) + entries meter (local D / R scans)', local_affine='entries meter (row support scan)',
    _affine_build='entries meter (image tables: binary-involved views evaluated per image row; categorical-only views copied entry by entry; the constant-image check reads one entry)',
    quota_for='declared quota sizing from table SIZES (len), not a read')


class ZeroEvidence(Exception):
    def __init__(self, proof): super().__init__('ZERO_EVIDENCE'); self.proof = proof


class CompileStop(Exception):
    """a controlled interruption at a consistent point: kind in ('deadline', 'reference_done', 'cancelled', 'quota'); the compiled state is the LAST COMMIT"""
    def __init__(self, kind, op=None): super().__init__(kind); self.kind = kind; self.op = op


def tick(C, quota=None, op=None):
    """called inside every costly loop; EVERY tick is a controller service point (sixth review, CQR-R5-02): (1) the controller hook (deadline / reference parity / reference
    completion / memory cancellation) runs FIRST and may raise CompileStop -- its stops take precedence over the operator quota; (2) only then the operator quota (CompileStop('quota')
    => the operator stops; its commits stay). The charged-since-service counter restarts only when the controller has actually been invoked, so a quota exit never leaves a pending
    service obligation undischarged and `max_gap` measures the spacing of ACTUAL controller invocations. The compiled state is always a committed one when this is called."""
    C.ticks += 1
    if C.acc_since > C.max_gap: C.max_gap = C.acc_since
    C.acc_since = 0
    fn = getattr(C, 'service', None)
    if fn is not None: C.service_calls += 1; fn(op)
    if quota is not None and C.work.total() >= quota: raise CompileStop('quota', op)


class _Ticker:
    """charged-unit accountant of ONE operator. CONTRACT (fourth review CQR-R3-04; fifth review CQR-R4-01 / 02): work is posted through per-loop meters (`_Meter`) that compare
    their pending count with the REMAINING allowance (TICK_ENTRIES - units charged since the last service point; ONE counter on the compiled state) after every indivisible step
    (<= max_step_charge units) and post as soon as the allowance is reached. EXACTLY-ONCE: a meter transfers ownership of its pending count to the ledger BEFORE the service
    point runs, so a stop raised by the service point (quota / deadline / reference_done / cancelled) leaves nothing pending and a later flush posts nothing again; a meter used
    as a context manager flushes its completed tail on EVERY exit -- with a service point on a normal exit, WITHOUT one while an exception propagates (the tail is < the
    allowance, so no service point is missed, and the original typed stop is never replaced). Constructing a ticker registers it as the compiled state's ACTIVE ticker, so work
    delegated by `commit` (witness validation) inherits the operator's quota and service context. A post larger than the allowance + max_step_charge - 1 is charged and then
    reported as a contract violation."""
    __slots__ = ('C', 'quota', 'op', 'max_post')
    def __init__(self, C, quota, op): self.C = C; self.quota = quota; self.op = op; self.max_post = 0; C.active = self
    @property
    def acc(self): return self.C.acc_since                        # charged units since the last service point
    def room(self): return TICK_ENTRIES - self.C.acc_since        # >= 1: the units that may still be performed before the next service point
    def _charge(self, attr, k):
        setattr(self.C.work, attr, getattr(self.C.work, attr) + k); self.C.acc_since += k
        if k > self.max_post: self.max_post = k
    def _post(self, attr, k):
        """charge k units (already performed) and service if the allowance is reached; the charge happens FIRST, so a stop raised by the service point never uncharges it"""
        room = TICK_ENTRIES - self.C.acc_since
        self._charge(attr, k)
        if self.C.acc_since >= TICK_ENTRIES: tick(self.C, self.quota, self.op)
        if k > room + POLICY['max_step_charge'] - 1: raise AssertionError('post of %d units exceeded the remaining service allowance %d by more than %d (CQR-R3-04 contract; the units ARE charged)' % (k, room, POLICY['max_step_charge'] - 1))
    def entries(self, k): self._post('entries', k)
    def ratops(self, k): self._post('ratops', k)
    def evals(self, k): self._post('evals', k)
    def meter(self, attr='entries'): return _Meter(self, attr)
    def ratop_each(self, iterable, fn):
        """map fn over an iterable, charging ONE rational operation per element through a meter (the computation is split at the remaining allowance; a failing fn leaves every
        completed operation charged exactly once)"""
        out = []
        with _Meter(self, 'ratops') as m:
            for x in iterable: out.append(fn(x)); m.add()
        return out


class _Meter:
    """per-loop counter bound to a ticker (or to a plain Work when there is no ticker: the checker's helpers charge lumps without service points). add(k) records k units of
    work DONE; when the pending count reaches the ticker's remaining allowance it is posted -- ownership moves to the ledger BEFORE the post (exactly once). Use as a context
    manager: the completed tail is flushed on every exit (serviced on a normal exit; charge-only while an exception propagates)."""
    __slots__ = ('T', 'attr', 'n', 'room', 'work')
    def __init__(self, T, attr='entries', work=None):
        self.T = T; self.attr = attr; self.n = 0; self.work = work; self.room = (TICK_ENTRIES - T.C.acc_since) if T is not None else None
    def add(self, k=1):
        self.n += k
        if self.T is not None and self.n >= self.room:
            k_ = self.n; self.n = 0                                 # ownership transferred before the post: nothing stays pending if the service point raises
            self.T._post(self.attr, k_); self.room = TICK_ENTRIES - self.T.C.acc_since
    def flush(self, service=True):
        k_ = self.n; self.n = 0
        if not k_: return
        if self.T is not None:
            if service: self.T._post(self.attr, k_)
            else: self.T._charge(self.attr, k_)                   # while an exception propagates: the completed tail is charged, no second service point, the stop is kept
        elif self.work is not None: setattr(self.work, self.attr, getattr(self.work, self.attr) + k_)
    def __enter__(self): return self
    def __exit__(self, et, ev, tb): self.flush(service=(et is None)); return False


KEEP = object()        # commit(witness=KEEP): the witness is unchanged (allowed only when the variable domain is unchanged)


def _witness_problem(cards, views, w, T=None):
    """None if w is a complete in-range assignment of the model (cards, views) with strictly positive weight; else the reason (T: the ticker charging one evaluation per view)"""
    n = len(cards)
    if not isinstance(w, dict) or sorted(w.keys()) != list(range(n)): return 'witness domain %s differs from the variables 0..%d' % (sorted(w.keys())[:6] if isinstance(w, dict) else type(w).__name__, n - 1)
    if any(not isinstance(w[v], int) or not (0 <= w[v] < cards[v]) for v in range(n)): return 'witness state out of range for the resulting domain'
    wt = F(1)
    with _Meter(T, 'evals') as m:
        for v in views:
            wt *= v.at(cards, w); m.add()
            if wt == 0: return 'witness has zero weight on the resulting model'
    return None


def _witness_renumbered(w, cards, removed):
    """the witness with the variables `removed` deleted and the rest renumbered (the same map as _renumbered)"""
    if w is None: return None
    keep = [v for v in range(len(cards)) if v not in removed]; new = {v: i for i, v in enumerate(keep)}
    return {new[v]: w[v] for v in keep if v in w}


class Compiled:
    """the compiled task state: a sequence of immutable committed snapshots with a journal of certificate records"""
    def __init__(self, cards, views, queries, decoder, work, bias, normalizer_task=False):
        self.cards = list(cards); self.views = list(views); self.queries = list(queries); self.decoder = list(decoder); self.work = work; self.bias = list(bias)
        self.certs = []; self.scalars = []; self.constant_scalars = []; self.witness = None; self.normalizer_task = normalizer_task; self.affine_done = False; self.service = None; self.constant_queries = {}
        self.ticks = 0; self.commits = 0; self.fault = None; self._last = None; self.allowance = None; self.max_gap = 0; self.acc_since = 0; self.active = None; self.service_calls = 0; self.service_calls_evidence = 0

    def n(self): return len(self.cards)
    def measure(self): return (len(self.cards), sum(self.cards), sum(v.size() for v in self.views) + sum(_qsize(q) for q in self.queries))
    def snapshot_json(self):
        return dict(cards=list(self.cards), factors=[v.to_json() for v in self.views], queries=[_q_json(q) for q in self.queries], decoder=_dec_json(self.decoder), bias=[str(b) for b in self.bias],
                    scalars=list(self.scalars), constant_queries={str(k): str(v) for k, v in self.constant_queries.items()}, affine_done=self.affine_done,
                    witness=({str(k): v for k, v in self.witness.items()} if self.witness is not None else None))
    def state(self):
        """the committed state as a shallow structure (every object inside is immutable by the transaction rule)"""
        return dict(cards=list(self.cards), views=list(self.views), queries=list(self.queries), decoder=list(self.decoder), bias=list(self.bias), certs=list(self.certs), scalars=list(self.scalars),
                    constant_scalars=list(self.constant_scalars), witness=self.witness, affine_done=self.affine_done, constant_queries=dict(self.constant_queries), commits=self.commits)
    def commit(self, rec, cards=None, views=None, queries=None, decoder=None, bias=None, scalars_add=(), constant_queries=None, witness=KEEP, affine_done=None):
        """ATOMIC: every new object was built beforehand; the swap is a sequence of plain attribute assignments with no computation; the record is appended last.
        WITNESS LIFECYCLE (fourth review, CQR-R3-03): the positivity witness is model-dependent state. A commit that changes the variable domain (`cards`) MUST carry the
        witness in the new coordinates (or None = invalidated); keeping the old one by omission is refused. The committed witness is validated on the RESULTING model
        (complete domain, in-range states, strictly positive weight); an invalid one is dropped with the reason recorded (never kept, never a fault)."""
        _fault_point(self, rec.get('op'), 'before_swap')
        if witness is KEEP and cards is not None and self.witness is not None: raise ValueError('commit of %s changes the variable domain without transforming or invalidating the positivity witness (CQR-R3-03 invariant)' % rec.get('op'))
        new_cards = list(cards) if cards is not None else self.cards; new_views = list(views) if views is not None else self.views
        w_new = self.witness if witness is KEEP else (dict(witness) if witness is not None else None); w_drop = None
        if w_new is not None:
            # charged + serviced under the ACTIVE operator's ticker (its quota, deadline and service context; fifth review CQR-R4-02); a replay without a producer quota is the
            # explicit quota-less context. Nothing has been swapped yet: a stop raised here leaves the state at the last commit with every unit charged
            T_ = self.active if (self.active is not None and self.active.C is self) else _Ticker(self, None, rec.get('op'))
            bad = _witness_problem(new_cards, new_views, w_new, T_)
            if bad: w_drop = bad; w_new = None
        if cards is not None: self.cards = list(cards)
        if views is not None: self.views = list(views)
        if queries is not None: self.queries = list(queries)
        if decoder is not None: self.decoder = list(decoder)
        if bias is not None: self.bias = list(bias)
        if scalars_add: self.scalars = list(self.scalars) + list(scalars_add)
        if constant_queries is not None: self.constant_queries = dict(constant_queries)
        self.witness = w_new
        if affine_done is not None: self.affine_done = affine_done
        if any(b < 0 for b in self.bias): raise ValueError('negative bias ledger after %s (CQR-R2-02 invariant 0 <= bias_j)' % rec.get('op'))
        if self.allowance is not None and any(self.bias[j] > self.allowance[j] for j in range(len(self.bias))): raise ValueError('bias ledger exceeds the allowed reserve after %s' % rec.get('op'))
        rec = dict(rec); rec['kind'] = 'commit'; rec['seq'] = self.commits
        if w_drop: rec['witness_dropped'] = w_drop
        if witness is not KEEP and witness is not None and self.witness is not None: rec['witness_after'] = {str(k): v for k, v in self.witness.items()}
        self.commits += 1; self.certs = list(self.certs) + [rec]; self._last = self.state()
        _fault_point(self, rec.get('op'), 'after_commit')
        return rec
    def decline(self, op, reason, **extra):
        rec = dict(kind='decline', op=op, declined=reason, **extra); self.certs = list(self.certs) + [rec]; return rec
    def commit_records(self): return [c for c in self.certs if c.get('kind') == 'commit']


def _fault_point(C, op, where):
    """qualification fault injection (never a production path): C.fault = dict(op, where in ('build', 'before_swap', 'after_commit'), k = the commit index of `op` at which to fail)"""
    f = getattr(C, 'fault', None)
    if not f or f.get('op') != op or f.get('where') != where: return
    k = f.get('k', 0); n_op = sum(1 for c in C.certs if c.get('kind') == 'commit' and c.get('op') == op)
    if where == 'after_commit': n_op -= 1          # the record of the current commit is already in the journal
    if n_op == k: raise RuntimeError('INJECTED optional fault in %s at %s (commit %d of this operator; qualification control; never a production run)' % (op, where, k))


def _qsize(q): return q['f'].size() if q['kind'] == 'expectation' else q['h'].size() + q['g'].size()
def _q_json(q):
    d = dict(name=q['name'], kind=q['kind'], output=q['output'], orig_index=q['orig_index'])
    if q['kind'] == 'expectation': d['f'] = q['f'].to_json()
    else: d['h'] = q['h'].to_json(); d['g'] = q['g'].to_json()
    return d
def _dec_json(dec):
    out = []
    for d in dec:
        e = dict(d)
        if 'states' in e and isinstance(e['states'], dict): e['states'] = {str(k): [[o, str(w)] for o, w in v] for k, v in e['states'].items()}
        out.append(e)
    return out
def q_views(q): return [q['f']] if q['kind'] == 'expectation' else [q['h'], q['g']]
def q_scope(q): return set().union(*(set(v.scope) for v in q_views(q)))
def _q_with(q, **views):
    """a NEW query dict with replaced view objects (the committed one is never mutated)"""
    n = dict(q); n.update(views); return n
def _q_map(q, fn):
    return _q_with(q, f=fn(q['f'])) if q['kind'] == 'expectation' else _q_with(q, h=fn(q['h']), g=fn(q['g']))


# ======================================================================================================================
# evidence restriction (the first record of every journal)
# ======================================================================================================================
def from_task(task, work=None, service=None):
    """evidence-restricted compiled task over the FREE original variables (observed variables: decoder 'fixed'); factor and query tables restricted to the evidence.
    `service` (optional) is the controller hook: the restriction scan is charged optional work and ticks every TICK_ENTRIES entries (R3: evidence restriction is a scan too)"""
    work = work or Work(); m = task['model']; cards0 = m['cards']; ev = m.get('evidence', {}); n0 = len(cards0)
    free = [v for v in range(n0) if v not in ev]; new_of = {v: i for i, v in enumerate(free)}; cards = [cards0[v] for v in free]
    acc = [0]; ev_calls = [0]
    ev_gap = [0]
    def charge(k):
        work.entries += k; acc[0] += k
        if acc[0] >= TICK_ENTRIES:
            if acc[0] > ev_gap[0]: ev_gap[0] = acc[0]          # the spacing of the evidence phase's actual controller invocations enters max_service_gap (eighth review, correction 2)
            acc[0] = 0
            if service is not None: ev_calls[0] += 1; service('evidence')
    def restrict(scope, values):
        ns = tuple(new_of[v] for v in scope if v not in ev); vals = []
        for xs, w in zip(product(*(range(cards0[v]) for v in scope)), values):
            charge(1)
            if all(v in new_of or ev[v] == s for v, s in zip(scope, xs)): vals.append(F(w))
        return ns, vals
    views = []; constant_scalars = []           # TASK-LOCAL (review CQR-07)
    for fi, f in enumerate(m['factors']):
        ns, vals = restrict(f['scope'], f['values'])
        if not ns:
            if vals[0] == 0: raise ZeroEvidence(dict(kind='fully_observed_factor_zero', factor=fi))
            if vals[0] != 1: constant_scalars.append(dict(factor=fi, value=str(vals[0])))      # a positive constant factor: cancelled for normalized tasks (symbolic scalar), kept as an exact scalar for normalizer tasks
            continue
        views.append(View('table', ns, tuple(vals)))
    queries = []
    for j, q in enumerate(task['queries']):
        if q.kind == 'expectation':
            ns, vals = restrict(q.f.scope, q.f.values); queries.append(dict(name=q.name, kind='expectation', f=View('table', ns, tuple(vals)), output=q.output, orig_index=j))
        else:
            nh, vh = restrict(q.h.scope, q.h.values); ng, vg = restrict(q.g.scope, q.g.values); queries.append(dict(name=q.name, kind='ratio', h=View('table', nh, tuple(vh)), g=View('table', ng, tuple(vg)), output=q.output, orig_index=j))
    decoder = [dict(kind='fixed', state=ev[v]) if v in ev else dict(kind='map', var=new_of[v], states={a: [(a, F(1))] for a in range(cards0[v])}) for v in range(n0)]
    normalizer_task = bool((task.get('query_spec') or {}).get('normalizer_task'))
    C = Compiled(cards, views, queries, decoder, work, [F(0)] * len(task['queries']), normalizer_task=normalizer_task)
    C.constant_scalars = constant_scalars; C.service = service
    C.certs = [dict(kind='evidence', op='evidence', evidence={str(k): v for k, v in sorted(ev.items())}, free=free, constant_factor_scalars=list(constant_scalars))]
    C.acc_since = acc[0]; C.service_calls = ev_calls[0]; C.service_calls_evidence = ev_calls[0]; C.max_gap = ev_gap[0]; C._last = C.state(); return C


# ======================================================================================================================
# helpers on views that are plain tables -- every helper RETURNS NEW objects and ticks inside its scan when given a ticker
# ======================================================================================================================
def _slice(view, cards, var, state, T=None):
    """the slice of a table view over the other scope variables at var = state, as a tuple in row-major order of the remaining scope (charged + serviced through T's meter)"""
    assert view.kind == 'table'; rest = [v for v in view.scope if v != var]; out = []; vals = view.values; scope = view.scope
    with _Meter(T, 'entries') as m:
        for xs in product(*(range(cards[v]) for v in rest)):
            x = dict(zip(rest, xs)); x[var] = state; i = 0
            for v in scope: i = i * cards[v] + x[v]
            out.append(vals[i]); m.add()
    return tuple(out)


def _replace_axis(view, cards, var, new_states, new_card, T=None):
    """a NEW table view with the axis `var` replaced: new_states[s'] = the OLD state whose slice represents new state s' (cards carry the OLD card of var)"""
    scope = view.scope; vals = []; old_cards = {v: cards[v] for v in scope}
    def idx(x):
        i = 0
        for v in scope: i = i * old_cards[v] + x[v]
        return i
    with _Meter(T, 'entries') as m:
        for xs in product(*((range(new_card) if v == var else range(old_cards[v])) for v in scope)):
            x = dict(zip(scope, xs)); x[var] = new_states[x[var]]; vals.append(view.values[idx(x)]); m.add()
    return View('table', scope, tuple(vals))


def _average_axis(view, cards, var, classes, weights, T=None):
    """query pullback for a quotient (NEW view): value at class C = sum_{a in C} weights[a] * old value at a"""
    scope = view.scope; vals = []
    def idx(x):
        i = 0
        for v in scope: i = i * cards[v] + x[v]
        return i
    with _Meter(T, 'entries') as m:                                   # one ENTRY per old value read (the weighted sum is arithmetic on the read value); the class sum is split at the remaining allowance (CQR-R3-04)
        for xs in product(*((range(len(classes)) if v == var else range(cards[v])) for v in scope)):
            x = dict(zip(scope, xs)); c = x[var]; s = F(0)
            for a in classes[c]: x[var] = a; s += weights[a] * view.values[idx(x)]; m.add()
            vals.append(s)
    return View('table', scope, tuple(vals))


def _remove_var_from_scope_fixed(view, cards, var, state, T=None):
    scope = view.scope; rest = tuple(v for v in scope if v != var); vals = []
    with _Meter(T, 'entries') as m:
        for xs in product(*(range(cards[v]) for v in rest)):
            x = dict(zip(rest, xs)); x[var] = state; i = 0
            for v in scope: i = i * cards[v] + x[v]
            vals.append(view.values[i]); m.add()
    return View('table', rest, tuple(vals))


def _renumbered(views, queries, decoder, cards, removed):
    """NEW views / queries / decoder / cards with the compiled variables `removed` (set) deleted from every scope; they must not occur in any scope any more"""
    keep = [v for v in range(len(cards)) if v not in removed]; new = {v: i for i, v in enumerate(keep)}
    def rv(v):
        # SCOPE-ONLY: the new view BORROWS the old view's immutable storage (the same tuple object; no entry is read or copied -- VIEW_STORAGE_RULE, ninth review CQR-R8-01)
        assert not (set(v.scope) & removed), 'variable still in a scope'
        if v.kind == 'affine': return View('affine', tuple(new[u] for u in v.scope), v.values, cat_scope=tuple(new[u] for u in v.cat_scope), zcols=tuple(new[u] for u in v.zcols), urows=v.urows)
        return View('table', tuple(new[u] for u in v.scope), v.values)
    nviews = [rv(v) for v in views]; nqueries = [_q_map(q, rv) for q in queries]; ndec = []
    for d in decoder:
        e = dict(d)
        if e['kind'] == 'map': e['var'] = new[e['var']]
        if e['kind'] == 'affine_map': e['zvars'] = [new[u] for u in e['zvars']]
        ndec.append(e)
    return nviews, nqueries, ndec, [cards[v] for v in keep]


# ======================================================================================================================
# operator A: support fixpoint, fixed substitution, leaf sum-out, component omission -- each local change is ONE atomic commit with a replayable record
# ======================================================================================================================
def _dead_states(C, var, T):
    """states of compiled variable var whose slice is identically zero in some incident table factor (read-only scan)"""
    inc = [v for v in C.views if v.kind == 'table' and var in v.scope]; dead = set()
    for v in inc:
        for s in range(C.cards[var]):
            sl = _slice(v, C.cards, var, s, T)
            if not any(sl): dead.add(s)
    return dead


def _support_apply(C, var, alive, T=None):
    """NEW state with only the states `alive` (ordered) of compiled variable var; tables / queries re-indexed; decoder maps composed"""
    def rv(v): return _replace_axis(v, C.cards, var, alive, len(alive), T) if var in v.scope else v
    views = [rv(v) for v in C.views]; queries = [_q_map(q, rv) for q in C.queries]; pos = {s: i for i, s in enumerate(alive)}; dec = []
    for d in C.decoder:
        if d['kind'] == 'map' and d['var'] == var: e = dict(d); e['states'] = {pos[s]: lst for s, lst in d['states'].items() if s in pos}; dec.append(e)
        else: dec.append(d)
    cards = list(C.cards); cards[var] = len(alive)
    w = C.witness
    if w is not None:
        if w.get(var) in pos: w = dict(w); w[var] = pos[w[var]]
        else: w = None                                   # a witness whose state died has zero weight: invalidated (never kept stale)
    _fault_point(C, 'support', 'build')
    return dict(cards=cards, views=views, queries=queries, decoder=dec, witness=w)


def support_fixpoint(C, quota):
    """remove compiled states whose slice is identically zero in some incident table factor; fixpoint; an empty domain => ZERO_EVIDENCE. ONE COMMIT PER RESTRICTED VARIABLE
    (record: var, alive, dead, pass); the quota / service hook is tested inside every slice scan"""
    changed = True; committed = 0; passes = 0; T = _Ticker(C, quota, 'support_fixpoint')
    while changed:
        changed = False; passes += 1
        for var in range(C.n()):
            tick(C, quota, 'support_fixpoint')
            dead = _dead_states(C, var, T)
            if not dead: continue
            alive = [s for s in range(C.cards[var]) if s not in dead]
            if not alive: raise ZeroEvidence(dict(kind='empty_domain_after_support_propagation', compiled_variable=var, pass_=passes))
            new = _support_apply(C, var, alive, T)
            C.commit(dict(op='support', var=var, alive=alive, dead=sorted(dead), pass_=passes), **new); committed += 1; changed = True
    return committed > 0


def _fixed_apply(C, T=None):
    """NEW state with every one-state compiled variable substituted into every factor / query and removed; constant factors become scalars (zero => ZERO_EVIDENCE)"""
    fixed = [v for v in range(C.n()) if C.cards[v] == 1]
    if not fixed: return None, []
    views = list(C.views); queries = list(C.queries); dec = list(C.decoder)
    for var in fixed:
        def rv(v): return _remove_var_from_scope_fixed(v, C.cards, var, 0, T) if var in v.scope else v
        views = [rv(v) for v in views]; queries = [_q_map(q, rv) for q in queries]; nd = []
        for d in dec:
            if d['kind'] == 'map' and d['var'] == var:
                lst = d['states'][0]
                nd.append(dict(kind='fixed', state=lst[0][0]) if len(lst) == 1 and lst[0][1] == 1 else dict(kind='fixed_mixture', states=lst))   # a class fixed as a whole: original states keep their conditional weights
            else: nd.append(d)
        dec = nd
    keep = []; scalars = []
    with _Meter(T, 'entries') as m:
        for i, v in enumerate(views):
            if not v.scope:
                c0 = v.values[0]; m.add()                                  # the constant check reads ONE entry of the new scalar table (charged; ninth review audit)
                if c0 == 0: raise ZeroEvidence(dict(kind='constant_factor_zero_after_substitution', factor=i))
                scalars.append(dict(kind='constant_factor', value=str(c0)))
            else: keep.append(v)
    nviews, nqueries, ndec, ncards = _renumbered(keep, queries, dec, C.cards, set(fixed))
    w = _witness_renumbered(C.witness, C.cards, set(fixed))        # the fixed variables have one state (0): the witness there is 0 by domain; the rest is renumbered
    _fault_point(C, 'fixed_substitution', 'build')
    return dict(cards=ncards, views=nviews, queries=nqueries, decoder=ndec, scalars_add=scalars, witness=w), fixed


def fixed_substitution(C):
    new, fixed = _fixed_apply(C, _Ticker(C, None, 'fixed_substitution'))
    if new is None: return False
    C.commit(dict(op='fixed_substitution', variables=fixed, scalars=new['scalars_add']), **new); return True


def _leaf_candidate(C):
    qscope = set().union(*(q_scope(q) for q in C.queries)) if C.queries else set()
    for var in range(C.n()):
        if var in qscope: continue
        inc = [i for i, v in enumerate(C.views) if var in v.scope]
        if len(inc) == 1 and C.views[inc[0]].kind == 'table': return var, inc[0]
    return None


def _leaf_apply(C, var, fi, T=None):
    """NEW state with factor fi summed over var (var removed); returns (state-kwargs, scalar-or-None)"""
    v = C.views[fi]; rest = tuple(u for u in v.scope if u != var); vals = []
    with _Meter(T, 'entries') as m:
        for xs in product(*(range(C.cards[u]) for u in rest)):
            x = dict(zip(rest, xs)); s = F(0)
            for a in range(C.cards[var]):
                x[var] = a; i = 0
                for u in v.scope: i = i * C.cards[u] + x[u]
                s += v.values[i]; m.add()
            vals.append(s)
    if not any(vals): raise ZeroEvidence(dict(kind='leaf_sum_identically_zero', compiled_variable=var, factor=fi))
    views = list(C.views); scalars = []
    if rest: views[fi] = View('table', rest, tuple(vals))
    else: scalars.append(dict(kind='leaf_sum_scalar', value=str(vals[0]))); views.pop(fi)
    dec = [dict(kind='summed') if (d['kind'] == 'map' and d['var'] == var) else d for d in C.decoder]
    nviews, nqueries, ndec, ncards = _renumbered(views, C.queries, dec, C.cards, {var})
    w = _witness_renumbered(C.witness, C.cards, {var})               # the summed factor at the witness's remaining coordinates is >= the old positive entry: positivity preserved
    _fault_point(C, 'leaf_sumout', 'build')
    return dict(cards=ncards, views=nviews, queries=nqueries, decoder=ndec, scalars_add=scalars, witness=w)


def leaf_sumout(C, quota):
    """a compiled variable outside every query scope occurring in exactly ONE table factor: replace that factor by its sum over the variable (no fill); ONE COMMIT PER LEAF
    (record: var, factor); positive scalar results cancel (normalized) / are retained (normalizer); a zero sum is ZERO_EVIDENCE only when the resulting factor is identically zero"""
    committed = 0; T = _Ticker(C, quota, 'leaf_sumout')
    while True:
        tick(C, quota, 'leaf_sumout')
        cand = _leaf_candidate(C)
        if cand is None: break
        var, fi = cand; new = _leaf_apply(C, var, fi, T)
        C.commit(dict(op='leaf_sumout', var=var, factor=fi, scalars=new['scalars_add']), **new); committed += 1
    return committed > 0


def _components(C):
    adj = {v: set() for v in range(C.n())}
    for v in C.views:
        for a in v.scope: adj[a] |= set(v.scope) - {a}
    seen = set(); comps = []
    for v in range(C.n()):
        if v in seen: continue
        todo = [v]; comp = {v}
        while todo:
            u = todo.pop()
            for w in adj[u]:
                if w not in comp: comp.add(w); todo.append(w)
        seen |= comp; comps.append(sorted(comp))
    return comps


def _omission_proofs(C, T=None):
    """query-free connected components with a positivity proof (all its tables strictly positive, or a witness restricted to it has positive weight)"""
    qscope = set().union(*(q_scope(q) for q in C.queries)) if C.queries else set(); omitted = []
    for comp in _components(C):
        if set(comp) & qscope: continue
        fv = [i for i, v in enumerate(C.views) if set(v.scope) <= set(comp)]
        proof = None; allpos = True
        with _Meter(T, 'entries', work=C.work) as m:
            for i in fv:
                for x in C.views[i].values:
                    m.add()
                    if not x > 0: allpos = False; break
                if not allpos: break
        if allpos: proof = dict(kind='all_tables_strictly_positive', factors=fv)
        elif C.witness is not None:
            w = F(1)
            with _Meter(T, 'evals', work=C.work) as m2:
                for i in fv: w *= C.views[i].at(C.cards, C.witness); m2.add()
            if w > 0: proof = dict(kind='witness_restricted_positive', factors=fv, witness={str(v): C.witness[v] for v in comp}, weight=str(w))
        if proof is None: continue
        omitted.append(dict(variables=comp, factors=fv, proof=proof))
    return omitted


def _omission_apply(C, omitted):
    drop_f = set(); drop_v = set()
    for o in omitted: drop_f |= set(o['factors']); drop_v |= set(o['variables'])
    views = [v for i, v in enumerate(C.views) if i not in drop_f]
    dec = [dict(kind='omitted') if (d['kind'] == 'map' and d['var'] in drop_v) else d for d in C.decoder]
    nviews, nqueries, ndec, ncards = _renumbered(views, C.queries, dec, C.cards, drop_v)
    w = _witness_renumbered(C.witness, C.cards, drop_v)
    _fault_point(C, 'component_omission', 'build')
    return dict(cards=ncards, views=nviews, queries=nqueries, decoder=ndec, witness=w, scalars_add=[dict(kind='omitted_component_mass', count=len(omitted), note='symbolic positive scalar; unknown numeric value; never reused as a numeric bound')])


def component_omission(C):
    """omit query-free connected components ONLY with a positivity proof; normalized tasks only; ONE commit for the whole set"""
    if C.normalizer_task: return False
    omitted = _omission_proofs(C, _Ticker(C, None, 'component_omission'))
    if not omitted: return False
    C.commit(dict(op='component_omission', omitted=omitted), **_omission_apply(C, omitted)); return True


# ======================================================================================================================
# operator B / C: proportional-slice quotient (exact) and the checked approximate variant -- ONE COMMIT PER VARIABLE
# ======================================================================================================================
def _signatures(C, var, T=None):
    """per state: tuple over incident table factors of (normalized slice tuple, pivot); None if an incident view is not a plain table (quotient declines)"""
    inc = [v for v in C.views if var in v.scope]
    if any(v.kind != 'table' for v in inc): return None, inc
    sig = {}
    for s in range(C.cards[var]):
        parts = []
        for v in inc:
            sl = _slice(v, C.cards, var, s, T)
            piv = next((x for x in sl if x), None)
            if piv is None: return None, inc            # a zero slice: support propagation must run first
            if T is not None: norm = tuple(T.ratop_each(sl, lambda x: x / piv))       # the normalization is performed AND charged in bounded chunks (CQR-R2-04)
            else: norm = tuple(x / piv for x in sl)
            parts.append((norm, piv))
        sig[s] = parts
    return sig, inc


def _quotient_build(C, var, classes, sig, inc, approx, T=None):
    """BUILD the post-quotient state of compiled variable var into `classes` (list of sorted state lists; representative = first state): NEW factor views (slices ->
    representative slices; a unary S_C combined with an existing unary), NEW query views (weighted average kappa_a / S_C), NEW decoder entries; returns (state kwargs, record)"""
    reps = [g[0] for g in classes]; kappa = {}; S = []
    with _Meter(T, 'ratops') as m:
        for g in classes:
            tot = F(0)
            for a in g:
                k = F(1)
                for fi in range(len(inc)):
                    k *= sig[a][fi][1] / sig[g[0]][fi][1]; m.add()
                kappa[a] = k; tot += k; m.add()
            S.append(tot)
    inc_idx = [C.views.index(v) for v in inc]; views = list(C.views)
    for i in inc_idx: views[i] = _replace_axis(C.views[i], C.cards, var, reps, len(classes), T)
    un_i = next((i for i, v in enumerate(views) if v.kind == 'table' and v.scope == (var,)), None)
    if un_i is not None:
        with _Meter(T, 'entries') as m:                              # one entry read of the NEW unary per class (charged; the product is arithmetic on the read value)
            uvals = []
            for i in range(len(classes)): uvals.append(views[un_i].values[i] * S[i]); m.add()
        views[un_i] = View('table', (var,), tuple(uvals))
    else: views.append(View('table', (var,), tuple(S)))
    weights = {a: kappa[a] / S[ci] for ci, g in enumerate(classes) for a in g}
    def rq(v): return _average_axis(v, C.cards, var, classes, weights, T) if var in v.scope else v
    queries = [_q_map(q, rq) for q in C.queries]
    dec = []
    for d in C.decoder:
        if d['kind'] == 'map' and d['var'] == var:
            new = {}
            for ci, g in enumerate(classes):
                lst = []
                for a in g:
                    for (orig, w) in d['states'][a]: lst.append((orig, w * weights[a]))
                new[ci] = lst
            e = dict(d); e['states'] = new; dec.append(e)
        else: dec.append(d)
    cards = list(C.cards); cards[var] = len(classes)
    w = C.witness
    if w is not None: w = dict(w); w[var] = next(ci for ci, g in enumerate(classes) if w[var] in g)      # the class of the witness's state (the representative slice is a positive multiple of its own)
    rec = dict(op=('approx_quotient' if approx else 'exact_quotient_pass'), var=var, classes=classes, representatives=reps, kappa={str(a): str(k) for a, k in kappa.items()}, S=[str(s) for s in S], incident_factors=inc_idx, approx=approx)
    _fault_point(C, rec['op'], 'build')
    return dict(cards=cards, views=views, queries=queries, decoder=dec, witness=w), rec


def _classes_of(C, var, sig, inc):
    if not inc: sig = {s: [] for s in range(C.cards[var])}
    groups = {}
    for s in range(C.cards[var]): groups.setdefault(tuple(p[0] for p in sig[s]), []).append(s)
    classes = [sorted(g) for g in groups.values()]; classes.sort(key=lambda g: g[0]); return classes


def exact_quotient_pass(C, quota, hook=None):
    """one complete pass over the compiled variables in canonical order (manuscript §3.1): classes of equal normalized incident slices; ONE COMMIT per variable with >= 2
    states in some class. A variable with NO incident factor has identical (empty) slices: all its states form one class (kappa = 1, S = d: the uniform marginal through the
    decoder). hook(kind, var, classes, sig, inc) is called BEFORE each commit (the checker verifies the step on the exact pre-step state). The quota / service hook is
    tested inside every slice scan; a CompileStop leaves the state at the last commit (its records are already in the journal)."""
    committed = 0; T = _Ticker(C, quota, 'exact_quotient_pass'); var = 0
    while var < C.n():
        tick(C, quota, 'exact_quotient_pass')
        sig, inc = _signatures(C, var, T)
        if sig is None: var += 1; continue
        classes = _classes_of(C, var, sig, inc)
        if len(classes) == C.cards[var]: var += 1; continue
        if not inc: sig = {s: [] for s in range(C.cards[var])}
        if hook is not None: hook('exact', var, classes, sig, inc)
        new, rec = _quotient_build(C, var, classes, sig, inc, None, T)
        C.commit(rec, **new); committed += 1; var += 1
    return committed > 0


def _surrogate_ratio(C, var, inc, slices, groups, T=None):
    """R = prod_a (u_a / l_a) with l_a, u_a the extrema of phi/phi~ over ALL positive entries of incident factor a under the grouping; None if a mask mismatch"""
    R = F(1); bounds = []
    with _Meter(T, 'ratops', work=C.work) as m:            # performed work is charged exactly once on every exit (mask mismatch, stop, failure included)
        for fi in range(len(inc)):
            lo = hi = None
            for g in groups:
                r = g['rep']; sl_r = slices[r][fi]; piv_i = next((i for i, x in enumerate(sl_r) if x), None)
                if piv_i is None: return None, None
                for s in g['states']:
                    sl = slices[s][fi]
                    if tuple(bool(x) for x in sl) != tuple(bool(x) for x in sl_r): return None, None
                    c = sl[piv_i] / sl_r[piv_i]
                    for a, b in zip(sl, sl_r):
                        if a:
                            rho = a / (c * b); m.add()
                            lo = rho if lo is None or rho < lo else lo; hi = rho if hi is None or rho > hi else hi
            bounds.append((lo, hi)); R *= hi / lo
    return R, bounds


def approx_quotient(C, quota, allowance, hook=None):
    """operator C: for each variable (canonical order) try to merge states whose normalized slices are CLOSE: common zero masks; surrogate = scaled representative slice;
    ALL-entry ratio bounds per incident factor; beta = h(prod u/l) must fit min_j (allowance_j - bias_j); then the exact quotient of the surrogate. ONE COMMIT per merged
    variable (surrogate + quotient + bias together); declines when any incident view is not a plain table, when zero masks differ, or when the bias does not fit; a quota
    exhaustion inside the scan of a variable leaves that variable untouched (its commits of earlier variables stand) and records one decline."""
    if all(a <= 0 for a in allowance): return False
    committed = 0; T = _Ticker(C, quota, 'approx_quotient'); var = 0
    while var < C.n():
        try:
            tick(C, quota, 'approx_quotient')
            inc = [v for v in C.views if var in v.scope]
            if not inc or any(v.kind != 'table' for v in inc) or C.cards[var] < 2: var += 1; continue
            d = C.cards[var]
            slices = {s: [_slice(v, C.cards, var, s, T) for v in inc] for s in range(d)}
            masks = {s: tuple(tuple(bool(x) for x in sl) for sl in slices[s]) for s in range(d)}
            remaining = min(allowance[j] - C.bias[j] for j in range(len(C.bias))) if C.bias else F(0)
            if remaining <= 0: break
            groups = []; pairs = 0
            for s in range(d):
                placed = False
                for g in groups:
                    pairs += 1
                    if pairs > d * d: break
                    r = g['rep']
                    if masks[s] != masks[r]: continue
                    trial = [dict(gg) for gg in groups]; tg = trial[groups.index(g)]; tg['states'] = tg['states'] + [s]
                    R, _ = _surrogate_ratio(C, var, inc, slices, trial, T)
                    if R is None: continue
                    beta = (R - 1) / (R + 3)
                    if beta <= remaining: g['states'].append(s); placed = True; break
                if not placed: groups.append(dict(rep=s, states=[s]))
            if all(len(g['states']) == 1 for g in groups): var += 1; continue
            R, bounds = _surrogate_ratio(C, var, inc, slices, groups, T); beta = (R - 1) / (R + 3)
            if beta > remaining: var += 1; continue
            if hook is not None: hook('approx', var, groups, slices, inc, R, beta)          # the checker recomputes R / beta on the exact pre-step slices
            # BUILD the surrogate on NEW incident views: phi~(s, y) = c_a(s) phi(r, y) with c from the first common positive pivot
            sur = []
            for fi, v in enumerate(inc):
                scope = v.scope; rest = [u for u in scope if u != var]
                with _Meter(T, 'entries') as m:                       # the surrogate starts from a COPY of the pre-step table: every entry read is charged (ninth review audit; a stop here commits nothing)
                    vals = []
                    for w_ in v.values: vals.append(w_); m.add()
                with _Meter(T, 'ratops') as m:
                    for g in groups:
                        r = g['rep']; sl_r = slices[r][fi]; piv_i = next(i for i, x in enumerate(sl_r) if x)
                        for s in g['states']:
                            if s == r: continue
                            c = slices[s][fi][piv_i] / sl_r[piv_i]
                            for ri, xs in enumerate(product(*(range(C.cards[u]) for u in rest))):
                                x = dict(zip(rest, xs)); x[var] = s; i = 0
                                for u in scope: i = i * C.cards[u] + x[u]
                                vals[i] = c * sl_r[ri]; m.add()
                sur.append(View('table', scope, tuple(vals)))
            # the exact quotient of the surrogate (signatures on the surrogate views; the quotient build reads the surrogate through a temporary view list)
            saved_views = C.views; tmp = list(C.views)
            for v, sv in zip(inc, sur): tmp[C.views.index(v)] = sv
            C.views = tmp
            try:
                sig, inc2 = _signatures(C, var, T); classes = [sorted(g['states']) for g in groups]; classes.sort(key=lambda g: g[0])
                new, rec = _quotient_build(C, var, classes, sig, inc2, dict(R=str(R), beta=str(beta), factor_bounds=[(str(l), str(u)) for l, u in bounds], groups=[g['states'] for g in groups]), T)
            finally: C.views = saved_views
            bias = [b + beta for b in C.bias]
            C.commit(rec, bias=bias, **new); committed += 1; var += 1
        except CompileStop as cs:
            if cs.kind == 'quota': C.decline('approx_quotient', 'quota exhausted inside the scan of variable %d (nothing of this variable committed)' % var); break
            raise
    return committed > 0


# ======================================================================================================================
# operator A (symmetry): bounded proposer + generic verifier (constants only; no table change)
# ======================================================================================================================
def symmetry(C, quota):
    """candidates: global complement on all-binary compiled models; per-variable state swap. Verifier: the action maps the MULTISET of table factors to itself. For an
    involution tau, a query table with f(x) + f(tau x) = 2c everywhere becomes the constant c (recorded; published only with a positive-mass proof). ONE commit for all
    constants found. Declines on affine views."""
    if any(v.kind != 'table' for v in C.views) or not C.views: return False
    cands = []
    if all(c == 2 for c in C.cards): cands.append(dict(name='global_complement', perm=list(range(C.n())), state_maps=[[1, 0]] * C.n()))
    for var in range(min(C.n(), 64)):
        if C.cards[var] == 2:
            maps = [[0, 1]] * C.n(); maps = list(maps); maps[var] = [1, 0]; cands.append(dict(name='swap_var_%d' % var, perm=list(range(C.n())), state_maps=maps))
    found = []; consts_all = dict(C.constant_queries); T = _Ticker(C, quota, 'symmetry')
    for cand in cands:
        try: tick(C, quota, 'symmetry')
        except CompileStop as cs:
            if cs.kind == 'quota': break
            raise
        if verify_symmetry_action(C.cards, C.views, cand, C.work, T):
            consts = {}
            for qi, q in enumerate(C.queries):
                if q['kind'] != 'expectation': continue
                c = _query_symmetric_constant(C.cards, q['f'], cand, C.work, T)
                if c is not None: consts[qi] = c
            if consts: found.append(dict(action=cand, constants={str(k): str(v) for k, v in consts.items()})); consts_all.update(consts)
    if not found: return False
    _fault_point(C, 'symmetry', 'build')
    C.commit(dict(op='symmetry', actions=found), constant_queries=consts_all); return True


def _apply_action(cand, x):
    y = [None] * len(x)
    for v, s in enumerate(x): y[cand['perm'][v]] = cand['state_maps'][v][s]
    return y


def verify_symmetry_action(cards, views, cand, work, T=None):
    """the action maps every table factor to a table factor of the multiset (as functions)"""
    perm = cand['perm']
    if sorted(perm) != list(range(len(cards))): return False
    if any(cards[perm[v]] != cards[v] or sorted(cand['state_maps'][v]) != list(range(cards[v])) for v in range(len(cards))): return False
    used = [False] * len(views)
    with _Meter(T, 'entries', work=work) as m:
        for v in views:
            img_scope = tuple(perm[u] for u in v.scope); match = None
            for i, w in enumerate(views):
                if used[i] or set(w.scope) != set(img_scope) or len(w.values) != len(v.values): continue
                ok = True
                for xs in product(*(range(cards[u]) for u in v.scope)):
                    x = {u: s for u, s in zip(v.scope, xs)}; y = {perm[u]: cand['state_maps'][u][s] for u, s in x.items()}
                    a_ = v.at(cards, x); m.add(); b_ = w.at(cards, y); m.add()            # each unit is charged AFTER the evaluation it counts (sixth review, CQR-R5-03)
                    if a_ != b_: ok = False; break
                if ok: match = i; break
            if match is None: return False
            used[match] = True
        return True


def _query_symmetric_constant(cards, f, cand, work, T=None):
    """c such that f(x) + f(tau x) = 2c for every x (tau an involution on f's scope); None otherwise"""
    perm = cand['perm']
    if any(perm[u] not in f.scope for u in f.scope): return None
    c = None
    with _Meter(T, 'entries', work=work) as m:
        for xs in product(*(range(cards[u]) for u in f.scope)):
            x = dict(zip(f.scope, xs)); y = {perm[u]: cand['state_maps'][u][s] for u, s in x.items()}; z = {perm[u]: cand['state_maps'][u][s] for u, s in y.items()}
            if z != x: return None
            fa = f.at(cards, x); m.add(); fb = f.at(cards, y); m.add(); s = (fa + fb) / 2
            if c is None: c = s
            elif s != c: return None
        return c


# ======================================================================================================================
# operator E: concentration certificate and influence deletion
# ======================================================================================================================
def _unary_product_argmax(C, var, T=None):
    best = None; bw = None
    with _Meter(T, 'entries', work=C.work) as m:
        for s in range(C.cards[var]):
            w = F(1)
            for v in C.views:
                if v.kind == 'table' and v.scope == (var,): w *= v.values[s]; m.add()
            if bw is None or w > bw: bw = w; best = s
    return best


def concentration(C, quota, allowance):
    """reduction note §4: propose x* (unary argmax), compute per-site ratio sums R_i from local ratio inequalities over every incident factor (zeros handled: 0/0 no
    constraint, pos/0 = infinity, all-zero bad slice = 0), t_i = R_i / (1 + R_i); certify |E f_j - f_j(x*)| <= sum_{i in scope(f_j)} t_i; accept only when it fits
    every query's remaining allowance. ONE commit (bias spent; witness recorded); returns the direct answer record or None."""
    if any(v.kind != 'table' for v in C.views) or any(q['kind'] != 'expectation' for q in C.queries) or not C.queries: return None
    if all(a <= 0 for a in allowance): return None
    T = _Ticker(C, quota, 'concentration')
    xstar = {var: _unary_product_argmax(C, var, T) for var in range(C.n())}
    wst = F(1)
    with _Meter(T, 'evals') as m:
        for v in C.views: wst *= v.at(C.cards, xstar); m.add()
    if wst == 0: C.decline('concentration', 'proposed assignment has zero weight (no positive witness)'); return None
    t = {}
    for var in range(C.n()):
        try: tick(C, quota, 'concentration')
        except CompileStop as cs:
            if cs.kind == 'quota': C.decline('concentration', 'quota exhausted during the ratio scans'); return None
            raise
        Ri = F(0); inf = False
        for s in range(C.cards[var]):
            if s == xstar[var]: continue
            r = F(1); zero_bound = False
            for v in C.views:
                if var not in v.scope: continue
                try:
                    sl_s = _slice(v, C.cards, var, s, T); sl_r = _slice(v, C.cards, var, xstar[var], T)
                except CompileStop as cs:
                    if cs.kind == 'quota': C.decline('concentration', 'quota exhausted during the ratio scans'); return None
                    raise
                bound = F(0); has_pos = False
                for a, b in zip(sl_s, sl_r):
                    if a == 0: continue
                    has_pos = True
                    if b == 0: bound = None; break
                    bound = max(bound, a / b)
                if not has_pos: r = F(0); zero_bound = True; break
                if bound is None: r = None; break
                r *= bound
            if zero_bound: continue
            if r is None: inf = True; break
            Ri += r
        t[var] = F(1) if inf else Ri / (1 + Ri)
    answers = {}; biases = {}
    # the answer of every requested query at x* is a table lookup: charged AFTER it completed through the operator's meter and serviced at the declared interval (eighth review,
    # CQR-R7-02); a controller stop inside the loop propagates (nothing committed: the journal, model and bias are the last commit), a quota stop is a typed decline
    try:
        with _Meter(T, 'evals') as m:
            for qi, q in enumerate(C.queries):
                b = min(F(1), sum(t[u] for u in q['f'].scope)) if q['f'].scope else F(0)
                if b > allowance[qi] - C.bias[qi]: C.decline('concentration', 'bias %s exceeds the allowance of query %d' % (b, qi), t={str(k): str(v) for k, v in t.items()}); return None
                answers[qi] = q['f'].at(C.cards, xstar); m.add(); biases[qi] = b
    except CompileStop as cs:
        if cs.kind == 'quota': C.decline('concentration', 'quota exhausted during the query evaluations at x* (nothing committed)'); return None
        raise
    rec = dict(op='concentration', xstar={str(k): v for k, v in xstar.items()}, weight=str(wst), t={str(k): str(v) for k, v in t.items()}, answers={str(k): str(v) for k, v in answers.items()}, bias={str(k): str(v) for k, v in biases.items()},
               query_scopes={str(qi): list(q['f'].scope) for qi, q in enumerate(C.queries)})
    bias = list(C.bias)
    for qi, b in biases.items(): bias[qi] += b                 # the certified bias is SPENT in the ledger (the publication is widened by it; tau shrinks)
    _fault_point(C, 'concentration', 'build')
    rec = C.commit(rec, bias=bias, witness=xstar); return dict(answers=answers, bias=biases, record=rec)


def _h(R): return (R - 1) / (R + 3)


def influence_deletion(C, quota, allowance, neumann_T=8):
    """reduction note §3: strictly positive table factors only (zeros decline); Cbar_ij = min(1, sum_a h(R_aij)); D_ai; alpha = max_i sum_j Cbar_ij < 1 required;
    deletion set: all non-unary factors first, then greedy by decreasing size; e = Neumann sum + tail; beta_j = sum_{i in scope(f_j)} e_i; ONE commit (deletion + bias)"""
    if any(v.kind != 'table' for v in C.views) or any(q['kind'] != 'expectation' for q in C.queries): return False
    if all(a <= 0 for a in allowance): return False
    T = _Ticker(C, quota, 'influence_deletion'); Cbar = {}; Dai = {}            # SPARSE: Cbar[i][j] exists only for pairs sharing a factor (no dense n x n table)
    # the strict-positivity APPLICABILITY scan is operator work: every entry read is charged through the ticker from the first read (seventh review, CQR-R6-02), so the quota,
    # the controller cadence and the exactly-once rule hold whether the scan ends at an early / middle / late hard zero, completes, or is stopped
    try:
        hard_zero = False
        with _Meter(T, 'entries') as m:
            for v in C.views:
                for x in v.values:
                    m.add()
                    if not x > 0: hard_zero = True; break
                if hard_zero: break
    except CompileStop as cs:
        if cs.kind == 'quota': C.decline('influence_deletion', 'quota exhausted during the applicability scan'); return False
        raise
    if hard_zero: C.decline('influence_deletion', 'hard zeros remain: the strictly positive comparison operator does not apply'); return False
    def cb(i, j): return Cbar.get(i, {}).get(j, F(0))
    try:
        for fi, v in enumerate(C.views):
            if len(v.scope) < 1: continue
            sc = v.scope
            for i in sc:
                tick(C, quota, 'influence_deletion'); rest = [u for u in sc if u != i]; best = F(1)
                with _Meter(T, 'entries') as m:
                    for xs in product(*(range(C.cards[u]) for u in rest)):
                        x = dict(zip(rest, xs)); vals = []
                        for s_ in range(C.cards[i]): x[i] = s_; vals.append(v.at(C.cards, x)); m.add()
                        best = max(best, max(vals) / min(vals))
                Dai[(fi, i)] = best
                for j in sc:
                    if j == i: continue
                    rest2 = [u for u in sc if u not in (i, j)]; Rmax = F(1)
                    with _Meter(T, 'entries') as m:
                        for xs in product(*(range(C.cards[u]) for u in rest2)):
                            x = dict(zip(rest2, xs))
                            for u_ in range(C.cards[i]):
                                for v_ in range(u_ + 1, C.cards[i]):
                                    qs = []
                                    for s_ in range(C.cards[j]):
                                        x[i] = u_; x[j] = s_; a = v.at(C.cards, x); m.add(); x[i] = v_; b = v.at(C.cards, x); m.add(); qs.append(a / b)
                                    Rmax = max(Rmax, max(qs) / min(qs))
                    Cbar.setdefault(i, {})[j] = min(F(1), cb(i, j) + _h(Rmax))
    except CompileStop as cs:
        if cs.kind == 'quota': C.decline('influence_deletion', 'quota exhausted during the local scans'); return False
        raise
    alpha = max((sum(row.values()) for row in Cbar.values()), default=F(0))
    if alpha >= 1: C.decline('influence_deletion', 'alpha = %s >= 1: the contraction condition fails (not a statement about the model)' % alpha); return False
    sites = sorted({i for v in C.views for i in v.scope})
    def bias_of(dset):
        bbar = {i: min(F(1), sum(_h(Dai[(fi, i)]) for fi in dset if i in C.views[fi].scope)) for i in sites}
        e = {i: F(0) for i in sites}; term = dict(bbar)
        for _ in range(neumann_T):
            for i in sites: e[i] += term[i]
            term = {i: sum(cij * term[j] for j, cij in Cbar.get(i, {}).items()) for i in sites}
        tail = (alpha ** neumann_T) * (max(bbar.values()) if bbar else F(0)) / (1 - alpha)
        e = {i: x + tail for i, x in e.items()}
        return [min(F(1), sum(e.get(u, F(0)) for u in q['f'].scope)) for q in C.queries], e, bbar
    nonunary = [fi for fi, v in enumerate(C.views) if len(v.scope) >= 2]
    if not nonunary: return False
    chosen = None
    b_all, e_all, bb_all = bias_of(set(nonunary))
    if all(b_all[j] <= allowance[j] - C.bias[j] for j in range(len(C.queries))): chosen = set(nonunary); bias = b_all; e = e_all
    else:
        D = set(); cur = [F(0)] * len(C.queries)
        for fi in sorted(nonunary, key=lambda i: (-C.views[i].size(), i)):
            b, e_, _ = bias_of(D | {fi})
            if all(b[j] <= allowance[j] - C.bias[j] for j in range(len(C.queries))): D.add(fi); cur = b; e = e_
        if D: chosen = D; bias = cur
    if not chosen: C.decline('influence_deletion', 'no deletion set fits the allowance (alpha %s)' % alpha); return False
    nbias = [C.bias[j] + bias[j] for j in range(len(C.queries))]; views = [v for fi, v in enumerate(C.views) if fi not in chosen]
    _fault_point(C, 'influence_deletion', 'build')
    C.commit(dict(op='influence_deletion', deleted=sorted(chosen), alpha=str(alpha), bias=[str(b) for b in bias], e={str(i): str(x) for i, x in e.items()}, neumann_T=neumann_T, sparse_pairs=sum(len(r) for r in Cbar.values())), views=views, bias=nbias)
    return True


# ======================================================================================================================
# operator D: affine support (ONE commit; the representation change)
# ======================================================================================================================
def local_affine(view, cards, work, T=None):
    """for an all-binary table view: positive rows R; affine iff |R| == 2^rank(differences); returns (equations as (rowmask over view.scope bits, rhs)) or None"""
    k = len(view.scope)
    if any(cards[u] != 2 for u in view.scope) or k == 0: return None
    rows = []
    with _Meter(T, 'entries', work=work) as m:
        for i, w in enumerate(view.values):
            m.add()
            if w > 0: rows.append(i)        # row index i = bits of the scope in row-major order (first scope var = most significant bit)
    if not rows: raise ZeroEvidence(dict(kind='table_with_no_positive_entry'))
    r0 = rows[0]; rank, basis = gf2_rank_basis([r ^ r0 for r in rows])
    if len(rows) != 1 << rank: return None
    if rank == k: return []             # full support: no equation
    comp = []
    for cand in range(1, 1 << k):
        if all(bin(cand & b).count('1') % 2 == 0 for b in basis):
            red = gf2_reduce(cand, comp)
            if red: comp.append(red); comp.sort(reverse=True)
        if len(comp) == k - rank: break
    eqs = [(h, bin(h & r0).count('1') % 2) for h in comp]
    return eqs


def _affine_build(C, quota, T):
    """collect local equations over the compiled BINARY variables; eliminate globally; inconsistency => ZERO_EVIDENCE; otherwise x_bin = c + B z with pivot-free z; NEW views /
    queries / decoder / cards; returns (state kwargs, record) or (None, None) when nothing nontrivial was found"""
    bin_vars = [v for v in range(C.n()) if C.cards[v] == 2]
    if not bin_vars: return None, None
    pos = {v: i for i, v in enumerate(bin_vars)}; nb = len(bin_vars); eqs = []; local = []
    for fi, v in enumerate(C.views):
        tick(C, quota, 'affine')
        if not all(C.cards[u] == 2 for u in v.scope): continue
        le = local_affine(v, C.cards, C.work, T)
        if not le: continue
        local.append(dict(factor=fi, equations=[(h, b) for h, b in le]))
        for h, b in le:
            row = 0
            for bit in range(len(v.scope)):
                if (h >> (len(v.scope) - 1 - bit)) & 1: row |= 1 << pos[v.scope[bit]]
            eqs.append((row, b))
    if not eqs: return None, None
    aug = [(r | (b << nb)) for r, b in eqs]; basis = []
    for r in aug:
        for bb in basis:
            if (r ^ bb) & ((1 << nb) - 1) < r & ((1 << nb) - 1) or ((r ^ bb) & ((1 << nb) - 1)) == (r & ((1 << nb) - 1)) and (r ^ bb) < r: r ^= bb
        rr = r & ((1 << nb) - 1)
        if rr == 0:
            if r >> nb: raise ZeroEvidence(dict(kind='inconsistent_affine_equations', equations=len(eqs)))
            continue
        basis.append(r); basis.sort(reverse=True)
    basis = _rref(basis, nb); pivots = [(_msb(r & ((1 << nb) - 1))) for r in basis]; free_bits = [i for i in range(nb) if i not in pivots]
    rank = len(basis)
    if rank == 0: return None, None
    zidx = {fb: k for k, fb in enumerate(free_bits)}; crow = {}; Brow = {}
    for i in range(nb):
        if i in zidx: crow[i] = 0; Brow[i] = 1 << zidx[i]
    for r in basis:
        pv = _msb(r & ((1 << nb) - 1)); rhs = r >> nb; others = (r & ((1 << nb) - 1)) & ~(1 << pv); brow = 0
        for fb in free_bits:
            if (others >> fb) & 1: brow |= 1 << zidx[fb]
        crow[pv] = rhs; Brow[pv] = brow
    cat_vars = [v for v in range(C.n()) if C.cards[v] != 2]; newcards = [2] * len(free_bits) + [C.cards[v] for v in cat_vars]; cat_new = {v: len(free_bits) + i for i, v in enumerate(cat_vars)}
    def make_view(v):
        bin_in = [u for u in v.scope if C.cards[u] == 2]; cat_in = [u for u in v.scope if C.cards[u] != 2]
        if not bin_in:
            with _Meter(T, 'entries') as m:                       # the image of a categorical-only table is a copy: every entry read is charged (eighth review audit)
                vals = []
                for w_ in v.values: vals.append(w_); m.add()
            return View('table', tuple(cat_new[u] for u in v.scope), tuple(vals))
        rows = [Brow[pos[u]] for u in bin_in]; rank_u, ub = gf2_rank_basis(rows)
        coords = []
        for r in rows:
            coord = 0; x = r
            for k, bvec in enumerate(ub):
                if x ^ bvec < x: x ^= bvec; coord |= 1 << k
            assert x == 0; coords.append(coord)
        zcols = sorted({k for bvec in ub for k in range(len(free_bits)) if (bvec >> k) & 1})
        ub_local = []
        for bvec in ub:
            loc = 0
            for kk, zc in enumerate(zcols):
                if (bvec >> zc) & 1: loc |= 1 << kk
            ub_local.append(loc)
        rho = len(ub); vals = []
        with _Meter(T, 'entries') as m:
            for yb in product((0, 1), repeat=rho):
                for cs in product(*(range(C.cards[u]) for u in cat_in)):
                    x = dict(zip(cat_in, cs))
                    for ui, u in enumerate(bin_in):
                        bit = crow[pos[u]]
                        for k in range(rho):
                            if (coords[ui] >> k) & 1 and yb[k]: bit ^= 1
                        x[u] = bit
                    vals.append(v.at(C.cards, x)); m.add()
        return View('affine', tuple(zcols) + tuple(cat_new[u] for u in cat_in), tuple(vals), cat_scope=tuple(cat_new[u] for u in cat_in), zcols=tuple(zcols), urows=tuple(ub_local))
    new_views = [make_view(v) for v in C.views]
    queries = [_q_map(q, make_view) for q in C.queries]
    keep = []; scalars = []
    with _Meter(T, 'entries') as m:
        for v in new_views:
            if not v.scope:
                c0 = v.values[0]; m.add()                                  # the constant-image check reads ONE entry (charged; ninth review audit)
                if c0 == 0: raise ZeroEvidence(dict(kind='affine_image_zero'))
                scalars.append(dict(kind='affine_constant_factor', value=str(c0)))
            else: keep.append(v)
    dec = []
    for d in C.decoder:
        if d['kind'] == 'map':
            var = d['var']
            if C.cards[var] == 2:
                sts = d['states']; b = Brow[pos[var]]; zv = [k for k in range(len(free_bits)) if (b >> k) & 1]
                dec.append(dict(kind='affine_map', c=crow[pos[var]], zvars=zv, states={k: lst for k, lst in sts.items()}))
            else: e = dict(d); e['var'] = cat_new[var]; dec.append(e)
        else: dec.append(d)
    rec = dict(op='affine', local=local, rank=rank, binary_variables=bin_vars, free_bits=free_bits, c={str(i): crow[i] for i in range(nb)}, B={str(i): Brow[i] for i in range(nb)})
    w = _affine_witness(C.witness, bin_vars, pos, crow, Brow, free_bits, cat_vars, cat_new)
    _fault_point(C, 'affine', 'build')
    return dict(cards=newcards, views=keep, queries=queries, decoder=dec, scalars_add=scalars, affine_done=True, witness=w), rec


def _affine_witness(w, bin_vars, pos, crow, Brow, free_bits, cat_vars, cat_new):
    """the positivity witness in the affine coordinates: z_k = x[bin_vars[free_bits[k]]] (a free bit IS a binary variable: c = 0, B = e_k), categorical states renumbered;
    None when the old witness violates an equation x_u = c_u + <B_u, z> (impossible for a positive-weight witness: every positive row satisfies every local equation)"""
    if w is None: return None
    z = [w[bin_vars[fb]] for fb in free_bits]
    def parity(row):
        b = 0; k = 0
        while row:
            if row & 1 and z[k]: b ^= 1
            row >>= 1; k += 1
        return b
    for u in bin_vars:
        if w[u] != (crow[pos[u]] ^ parity(Brow[pos[u]])): return None
    out = {k: z[k] for k in range(len(free_bits))}
    for v in cat_vars: out[cat_new[v]] = w[v]
    return out


def affine(C, quota):
    """applied once, last; declines if no nontrivial equation or if any view is already affine"""
    if C.affine_done or any(v.kind != 'table' for v in C.views): return False
    new, rec = _affine_build(C, quota, _Ticker(C, quota, 'affine'))
    if new is None: return False
    C.commit(rec, **new); return True


def _msb(x): return x.bit_length() - 1
def _rref(basis, nb):
    basis = sorted(basis, reverse=True); out = []
    for r in basis:
        for o in out:
            pv = _msb(o & ((1 << nb) - 1))
            if (r >> pv) & 1: r ^= o
        if r & ((1 << nb) - 1): out.append(r)
    out.sort(reverse=True)
    for i in range(len(out)):
        pv = _msb(out[i] & ((1 << nb) - 1))
        for j in range(len(out)):
            if j != i and (out[j] >> pv) & 1: out[j] ^= out[i]
    return sorted(out, reverse=True)


# ======================================================================================================================
# the compile driver (reference policy order): ONE outcome representation per operator step
# ======================================================================================================================
def quota_for(task):
    m = task['model']; ent = sum(len(f['values']) for f in m['factors']) + sum((len(q.f.values) if q.kind == 'expectation' else len(q.h.values) + len(q.g.values)) for q in task['queries'])
    return max(50_000, 8 * ent)


NORMALIZER_FORBIDDEN = ('component_omission', 'approx_quotient', 'influence_deletion', 'concentration')      # TV-only / unknown-scalar / normalized-only rewrites (manuscript §9)


def effective_operators(arm_enabled, task):
    """the ONE task-effective operator policy shared by the producer and the checker (review CQR-08): the arm's set minus the rewrites a normalizer task forbids"""
    en = set(arm_enabled)
    if (task.get('query_spec') or {}).get('normalizer_task'): en -= set(NORMALIZER_FORBIDDEN)
    return en


def _save_state(C): return C.state()
def _restore_state(C, s):
    """belt-and-braces: every operator builds NEW objects and commits atomically, so after an exception the state already equals the last commit; this restores the
    attribute tuple from the saved snapshot (whose objects are immutable) in case an operator ever assigned an attribute outside commit()"""
    C.cards = list(s['cards']); C.views = list(s['views']); C.queries = list(s['queries']); C.decoder = list(s['decoder']); C.bias = list(s['bias']); C.certs = list(s['certs']); C.scalars = list(s['scalars'])
    C.constant_scalars = list(s['constant_scalars']); C.witness = s['witness']; C.affine_done = s['affine_done']; C.constant_queries = dict(s['constant_queries']); C.commits = s['commits']


def compile_task(task, enabled=None, deadline=None, work=None, service=None, fault=None):
    """returns (Compiled, log). `enabled` = the TASK-EFFECTIVE operator set (effective_operators). `service(op)` is called inside every costly scan (R3) and may raise
    CompileStop('deadline' | 'reference_done' | 'cancelled'); the driver returns the LAST COMMITTED model with log['interrupted'] set and every charge preserved.
    log['steps'][i] = dict(op, outcome, commits, work, measure_before, measure_after [, kind | error | reason]) with outcome in
    committed | no_change | declined | quota | interrupted | failed | disabled | skipped  -- the ONE representation of every operator outcome (R1).
    `fault` (qualification only): a string op name (fails before the operator starts) or dict(op, where in 'build' | 'before_swap' | 'after_commit', k) (fails mid-operator)."""
    enabled = set(POLICY['order']) if enabled is None else set(enabled); t0 = time.monotonic()
    def svc(op):
        if deadline is not None and time.monotonic() >= deadline: raise CompileStop('deadline', op)
        if service is not None: service(op)
    C = from_task(task, work, service=svc)
    C.service = svc; C.fault = fault if isinstance(fault, dict) else None
    C.allowance = [(task['epsilon'] / 4 if task['mode'] != 'EXACT_RATIONAL' else F(0))] * len(task['queries'])
    D = quota_for(task); allowance = [(task['epsilon'] / 4 if task['mode'] != 'EXACT_RATIONAL' else F(0))] * len(task['queries'])
    log = dict(quota=D, steps=[], direct=None, interrupted=None, failed=None, compiler_version=COMPILER_VERSION)
    def q_(k): return C.work.total() + D
    def step(name, fn):
        if log['interrupted']: log['steps'].append(dict(op=name, outcome='skipped', reason='interrupted', commits=0)); return False
        if log.get('failed'): log['steps'].append(dict(op=name, outcome='skipped', reason='optional_failure', commits=0)); return False
        if name not in enabled: log['steps'].append(dict(op=name, outcome='disabled', commits=0)); return False
        w0 = C.work.total(); m0 = C.measure(); c0 = C.commits; saved = _save_state(C); rec = dict(op=name, work=0, measure_before=m0); C.active = None
        try:
            if fault == name: raise RuntimeError('INJECTED optional fault in %s (qualification control; never a production run)' % name)      # before the operator starts
            r = fn()
            if C.commits > c0: rec.update(outcome='committed')
            elif any(c.get('kind') == 'decline' and c.get('op') == name for c in C.certs[len(saved['certs']):]): rec.update(outcome='declined', reason=[c['declined'] for c in C.certs[len(saved['certs']):] if c.get('kind') == 'decline'][-1][:160])
            else: rec.update(outcome='no_change')
        except CompileStop as cs:
            # the state IS the last commit (ticks only happen between commits); nothing to restore
            if cs.kind == 'quota': rec.update(outcome='quota')
            else: rec.update(outcome='interrupted', kind=cs.kind); log['interrupted'] = dict(op=name, kind=cs.kind)
            r = C.commits > c0
        except (ZeroEvidence, MemoryError): raise
        except Exception as ex:
            # an OPTIONAL FAILURE: the state equals the last commit by construction (asserted below); every unit spent stays charged; the failure is recorded; later operators are skipped
            last = C._last
            _restore_state(C, last if last is not None else saved)
            rec.update(outcome='failed', error='%s: %s' % (type(ex).__name__, str(ex)[:160])); log['failed'] = dict(op=name, error='%s: %s' % (type(ex).__name__, str(ex)[:160]), commits_kept=C.commits - c0)
            r = C.commits > c0
        rec.update(work=C.work.total() - w0, measure_after=C.measure(), commits=C.commits - c0); rec['committed'] = (rec['outcome'] == 'committed') or (C.commits > c0)
        if rec['outcome'] in ('quota', 'interrupted', 'failed') and C.commits > c0: rec['partial'] = True       # commits of this operator stand; the rest of it did not run
        log['steps'].append(rec); return r
    step('support_fixpoint', lambda: support_fixpoint(C, q_('support')))
    step('fixed_substitution', lambda: fixed_substitution(C))
    step('leaf_sumout', lambda: leaf_sumout(C, q_('leaf')))
    step('component_omission', lambda: component_omission(C))
    if step('exact_quotient_pass', lambda: exact_quotient_pass(C, q_('exact_quotient_pass'))):
        step('fixed_substitution', lambda: fixed_substitution(C)); step('leaf_sumout', lambda: leaf_sumout(C, q_('leaf')))
    step('symmetry', lambda: symmetry(C, q_('symmetry')))
    if task['mode'] != 'EXACT_RATIONAL':
        if step('approx_quotient', lambda: approx_quotient(C, q_('approx'), allowance)): step('fixed_substitution', lambda: fixed_substitution(C))
        direct = [None]
        def _conc():
            direct[0] = concentration(C, q_('conc'), allowance); return direct[0] is not None
        step('concentration', _conc)
        log['direct'] = direct[0]
        if direct[0] is None: step('influence_deletion', lambda: influence_deletion(C, q_('infl'), allowance))
        if direct[0] is None: step('leaf_sumout', lambda: leaf_sumout(C, q_('leaf')))
    else:
        for name in ('approx_quotient', 'concentration', 'influence_deletion'): log['steps'].append(dict(op=name, outcome='disabled', reason='EXACT_RATIONAL mode', commits=0))
    step('affine', lambda: affine(C, q_('affine')))
    C.service = None; C.fault = None; C.active = None              # the hooks are released with the task (the certificate serializer never sees them)
    log['wall_s'] = time.monotonic() - t0; log['work'] = C.work.snapshot(); log['final_measure'] = C.measure(); log['bias'] = [str(b) for b in C.bias]; log['commits'] = C.commits; log['ticks'] = C.ticks; log['max_service_gap'] = C.max_gap; log['controller_calls'] = C.service_calls; log['controller_calls_evidence'] = getattr(C, 'service_calls_evidence', 0); log['controller_calls_note'] = 'actual controller invocations INCLUDING the evidence-restriction phase (from_task; its share in controller_calls_evidence) and every compiler scan; max_service_gap is the largest number of charged units between two consecutive actual invocations INCLUDING the evidence phase (its leftover carries into the first compiler scan); frontier construction, deterministic bounds and the sampling laws are bulk phases outside this count (solve.py services around them)'
    return C, log


# ======================================================================================================================
# JOURNAL REPLAY (used by the checker): apply EXACTLY the recorded commits, verifying each on the pre-commit model
# ======================================================================================================================
def _canon_keys(d, n, what):
    """a record map keyed by compiled indices must have EXACTLY the canonical domain {'0', ..., 'n-1'} as distinct canonical decimal strings (no aliases such as '00' or ' 0',
    no extras, no missing); returns an error string or None (third review, CQR-R2-02)"""
    if not isinstance(d, dict): return '%s is not a map' % what
    keys = list(d.keys())
    if len(keys) != n or sorted(keys) != sorted(str(i) for i in range(n)): return '%s keys %s are not the canonical domain 0..%d' % (what, keys[:6], n - 1)
    return None


def _incident_indices(views, var):
    return [i for i, v in enumerate(views) if var in v.scope]


def _check_quotient_record_shape(cards, views, rc):
    """the structural part of a quotient record (exact or approximate) against the PRE-commit model: variable in range; incident_factors == the COMPLETE actual incident set (exact
    equality as a list of distinct in-range indices in increasing order); classes a genuine partition of the domain with sorted members and sorted by representative; kappa / S
    maps over the canonical key sets (CQR-R2-01)"""
    var = rc.get('var')
    if not isinstance(var, int) or not (0 <= var < len(cards)): return 'quotient record variable %r out of range' % (var,)
    inc = rc.get('incident_factors')
    if not isinstance(inc, list) or any(not isinstance(i, int) for i in inc): return 'incident_factors is not a list of indices'
    if inc != _incident_indices(views, var): return 'incident_factors %s differ from the complete incident set %s of variable %d on the pre-commit model' % (inc[:8], _incident_indices(views, var)[:8], var)
    classes = rc.get('classes')
    if not isinstance(classes, list) or not classes or any(not isinstance(g, list) or not g or any(not isinstance(s, int) for s in g) for g in classes): return 'classes are not non-empty lists of states'
    flat = [s for g in classes for s in g]
    if sorted(flat) != list(range(cards[var])) or len(flat) != len(set(flat)): return 'quotient classes are not a partition of the domain'
    if any(g != sorted(g) for g in classes) or [g[0] for g in classes] != sorted(g[0] for g in classes): return 'quotient classes are not in canonical order'
    if rc.get('representatives') != [g[0] for g in classes]: return 'representatives differ from the class minima'
    m = _canon_keys(rc.get('kappa'), cards[var], 'kappa'); 
    if m: return m
    if not isinstance(rc.get('S'), list) or len(rc['S']) != len(classes): return 'S has %s entries for %d classes' % (len(rc.get('S') or []), len(classes))
    return None


def verify_commit(C, rc, work, allowance):
    """independent verification of ONE recorded commit against the current (pre-commit) model; returns an error string or None; also returns derived facts for concentration"""
    op = rc.get('op'); cards = list(C.cards); views = [View.from_json(v.to_json()) for v in C.views]
    if op == 'support':
        var = rc.get('var'); alive = rc.get('alive'); dead = rc.get('dead')
        if not isinstance(var, int) or not (0 <= var < len(cards)) or not isinstance(alive, list) or not isinstance(dead, list): return 'support record malformed'
        if sorted(alive + dead) != list(range(cards[var])) or len(set(alive + dead)) != cards[var] or alive != sorted(alive) or not alive: return 'support record is not a partition of the domain'
        for s in dead:
            if not any(not any(_slice(v, cards, var, s)) for v in views if v.kind == 'table' and var in v.scope): return 'support: state %d of variable %d is not dead in any incident factor' % (s, var)
        work.entries += sum(v.size() for v in views if var in v.scope)
        return None
    if op == 'fixed_substitution':
        if sorted(rc['variables']) != [v for v in range(len(cards)) if cards[v] == 1]: return 'fixed substitution variables differ from the one-state variables'
        return None
    if op == 'leaf_sumout':
        var = rc.get('var'); fi = rc.get('factor')
        if not isinstance(var, int) or not isinstance(fi, int) or not (0 <= var < len(cards)) or not (0 <= fi < len(views)): return 'leaf record out of range'
        qs = set().union(*(q_scope(q) for q in C.queries)) if C.queries else set()
        if var in qs or [i for i, v in enumerate(views) if var in v.scope] != [fi] or views[fi].kind != 'table': return 'leaf: variable %d is not a leaf of factor %d' % (var, fi)
        return None
    if op == 'component_omission':
        if C.normalizer_task: return 'component omission on a normalizer task'
        qs = set().union(*(q_scope(q) for q in C.queries)) if C.queries else set()
        for o in rc.get('omitted', []):
            if set(o['variables']) & qs: return 'component omission touches a query scope'
            pr = o.get('proof') or {}
            if pr.get('kind') == 'all_tables_strictly_positive':
                if not all(all(x > 0 for x in views[i].values) for i in o['factors']): return 'component omission: positivity proof fails'
            elif pr.get('kind') == 'witness_restricted_positive':
                x = {int(k): v for k, v in pr['witness'].items()}; wgt = F(1)
                for i in o['factors']: wgt *= views[i].at(cards, x)
                if wgt <= 0: return 'component omission: witness has zero weight'
            else: return 'component omission: unknown proof kind'
            if any(not (set(views[i].scope) <= set(o['variables'])) for i in o['factors']) or any(i for i, v in enumerate(views) if set(v.scope) & set(o['variables']) and i not in o['factors']): return 'component omission: factor set is not the component'
        return None
    if op == 'exact_quotient_pass':
        m = _check_quotient_record_shape(cards, views, rc)
        if m: return m
        if rc.get('approx') not in (None, {}): return 'exact quotient record carries an approximate certificate'
        return verify_quotient_step(cards, views, rc, work)
    if op == 'approx_quotient':
        m = _check_quotient_record_shape(cards, views, rc)
        if m: return m
        ap = rc.get('approx') or {}; var = rc['var']; inc = [views[i] for i in rc['incident_factors']]
        if not isinstance(ap.get('groups'), list) or sorted(sorted(g) for g in ap['groups']) != sorted(rc['classes']): return 'approximate quotient groups differ from the classes'
        if any(g[0] != min(g) for g in ap['groups']): return 'approximate quotient group representatives are not the minima'
        if any(v.kind != 'table' for v in inc): return 'approximate quotient on a non-table view'
        slices = {s: [_slice(v, cards, var, s) for v in inc] for s in range(cards[var])}
        tmp = Compiled(cards, views, [], [], work, [])
        R2, bounds = _surrogate_ratio(tmp, var, inc, slices, [dict(rep=g[0], states=g) for g in ap.get('groups', [])])
        if R2 is None or str(R2) != ap.get('R') or str((R2 - 1) / (R2 + 3)) != ap.get('beta'): return 'approximate quotient certificate does not re-derive (R / beta)'
        if [g for g in ap.get('groups', [])] != [sorted(g) for g in ap.get('groups', [])] and sorted(sorted(g) for g in ap.get('groups', [])) != sorted(rc['classes']): return 'approximate quotient groups / classes differ'
        beta = F(ap['beta'])
        if any(C.bias[j] + beta > allowance[j] for j in range(len(C.bias))): return 'approximate quotient bias exceeds the allowance'
        # the exact quotient identities hold on the SURROGATE: rebuild it and run the exact verifier on it
        sur = []
        for fi, v in enumerate(inc):
            scope = v.scope; rest = [u for u in scope if u != var]; vals = list(v.values)
            for g in ap['groups']:
                r = g[0]; sl_r = slices[r][fi]; piv_i = next(i for i, x in enumerate(sl_r) if x)
                for s in g:
                    if s == r: continue
                    c = slices[s][fi][piv_i] / sl_r[piv_i]
                    for ri, xs in enumerate(product(*(range(cards[u]) for u in rest))):
                        x = dict(zip(rest, xs)); x[var] = s; i = 0
                        for u in scope: i = i * cards[u] + x[u]
                        vals[i] = c * sl_r[ri]
            sur.append(View('table', scope, tuple(vals)))
        sviews = list(views)
        for i, sv in zip(rc['incident_factors'], sur): sviews[i] = sv
        return verify_quotient_step(cards, sviews, rc, work)
    if op == 'symmetry':
        if not isinstance(rc.get('actions'), list) or not rc['actions']: return 'symmetry record without actions'
        for a in rc['actions']:
            if not isinstance(a.get('constants'), dict) or any((not qi.isdigit()) or str(int(qi)) != qi or not (0 <= int(qi) < len(C.queries)) for qi in a['constants']): return 'symmetry constants keyed outside the canonical query domain'
            if not verify_symmetry_action(cards, views, a['action'], work): return 'symmetry action does not verify'
            for qi, c in a['constants'].items():
                q = C.queries[int(qi)]
                if q['kind'] != 'expectation' or _query_symmetric_constant(cards, q['f'], a['action'], work) != F(c): return 'symmetric query constant does not re-derive'
        return None
    if op == 'concentration':
        K_ = len(C.queries)
        for nm in ('xstar', 't'):
            m = _canon_keys(rc.get(nm), len(cards), nm)
            if m: return m
        for nm in ('answers', 'bias'):
            m = _canon_keys(rc.get(nm), K_, nm)
            if m: return m
        if any(not isinstance(v, int) for v in rc['xstar'].values()): return 'xstar states are not integers'
        xs = {int(k): v for k, v in rc['xstar'].items()}
        if sorted(xs) != list(range(len(cards))) or any(not (0 <= xs[v] < cards[v]) for v in xs): return 'concentration: assignment outside the pre-step domains'
        try:
            if any(F(b) < 0 or F(b) > 1 for b in rc['bias'].values()): return 'concentration bias outside [0, 1]'
        except (ValueError, ZeroDivisionError): return 'concentration bias is not a rational'
        wst = F(1)
        for v in views: wst *= v.at(cards, xs)
        if wst <= 0: return 'concentration: the proposed assignment has zero weight on the pre-step model'
        if any(q['kind'] != 'expectation' for q in C.queries): return 'concentration on a ratio query'
        for qi, q in enumerate(C.queries):
            if str(q['f'].at(cards, xs)) != str(rc['answers'].get(str(qi))): return 'concentration answer of query %d does not re-derive (%s recorded, %s at x*)' % (qi, rc['answers'].get(str(qi)), q['f'].at(cards, xs))
        for var in range(len(cards)):
            Ri = F(0); inf = False
            for s in range(cards[var]):
                if s == xs[var]: continue
                r = F(1); zb = False
                for v in views:
                    if var not in v.scope: continue
                    sl_s = _slice(v, cards, var, s); sl_r = _slice(v, cards, var, xs[var]); bound = F(0); hp = False; work.entries += 2 * len(sl_s)
                    for a_, b_ in zip(sl_s, sl_r):
                        if a_ == 0: continue
                        hp = True
                        if b_ == 0: bound = None; break
                        bound = max(bound, a_ / b_)
                    if not hp: r = F(0); zb = True; break
                    if bound is None: r = None; break
                    r *= bound
                if zb: continue
                if r is None: inf = True; break
                Ri += r
            t = F(1) if inf else Ri / (1 + Ri)
            if str(t) != rc['t'][str(var)]: return 'concentration t_%d does not re-derive' % var
        for qi, q in enumerate(C.queries):
            bj = min(F(1), sum(F(rc['t'][str(u)]) for u in q['f'].scope)) if q['f'].scope else F(0)
            if str(bj) != str((rc.get('bias') or {}).get(str(qi))): return 'concentration bias of query %d does not re-derive' % qi
            if C.bias[qi] + bj > allowance[qi]: return 'concentration bias exceeds the allowance of query %d' % qi
        return None
    if op == 'influence_deletion':
        if not isinstance(rc.get('deleted'), list) or sorted(set(rc['deleted'])) != sorted(rc['deleted']) or any(not isinstance(i, int) or not (0 <= i < len(views)) for i in rc['deleted']): return 'influence deletion set is not a list of distinct in-range factors'
        if not isinstance(rc.get('bias'), list) or len(rc['bias']) != len(C.queries): return 'influence bias list has the wrong length'
        if any(F(b) < 0 or F(b) > 1 for b in rc['bias']): return 'influence bias outside [0, 1]'
        if any(x <= 0 for v in views for x in v.values): return 'influence deletion on a model with zeros'
        if F(rc['alpha']) >= 1: return 'influence deletion with alpha >= 1'
        if any(C.bias[j] + F(rc['bias'][j]) > allowance[j] for j in range(len(C.bias))): return 'influence bias exceeds the allowance'
        # re-derive alpha, e and the bias for the recorded deletion set with the SAME formulas (independent of the proposer's search)
        tmp = Compiled(cards, views, list(C.queries), [], Work(), list(C.bias)); tmp.normalizer_task = C.normalizer_task
        chk = _influence_recompute(tmp, set(rc['deleted']), rc.get('neumann_T', 8))
        if chk is None or str(chk['alpha']) != rc['alpha'] or [str(b) for b in chk['bias']] != rc['bias']: return 'influence alpha / bias do not re-derive for the recorded deletion set'
        return None
    if op == 'affine':
        return verify_affine_record(cards, views, rc, work)
    return 'unknown commit op %s' % op


def _influence_recompute(C, dset, neumann_T):
    """alpha, e, bias for a GIVEN deletion set (the certificate check of influence_deletion; same formulas as the proposer, no search)"""
    Cbar = {}; Dai = {}
    def cb(i, j): return Cbar.get(i, {}).get(j, F(0))
    for fi, v in enumerate(C.views):
        sc = v.scope
        for i in sc:
            rest = [u for u in sc if u != i]; best = F(1)
            for xs in product(*(range(C.cards[u]) for u in rest)):
                x = dict(zip(rest, xs)); vals = []
                for s_ in range(C.cards[i]): x[i] = s_; vals.append(v.at(C.cards, x))
                best = max(best, max(vals) / min(vals))
            Dai[(fi, i)] = best
            for j in sc:
                if j == i: continue
                rest2 = [u for u in sc if u not in (i, j)]; Rmax = F(1)
                for xs in product(*(range(C.cards[u]) for u in rest2)):
                    x = dict(zip(rest2, xs))
                    for u_ in range(C.cards[i]):
                        for v_ in range(u_ + 1, C.cards[i]):
                            qs = []
                            for s_ in range(C.cards[j]):
                                x[i] = u_; x[j] = s_; a = v.at(C.cards, x); x[i] = v_; b = v.at(C.cards, x); qs.append(a / b)
                            Rmax = max(Rmax, max(qs) / min(qs))
                Cbar.setdefault(i, {})[j] = min(F(1), cb(i, j) + _h(Rmax))
    alpha = max((sum(row.values()) for row in Cbar.values()), default=F(0))
    if alpha >= 1: return None
    sites = sorted({i for v in C.views for i in v.scope})
    bbar = {i: min(F(1), sum(_h(Dai[(fi, i)]) for fi in dset if i in C.views[fi].scope)) for i in sites}
    e = {i: F(0) for i in sites}; term = dict(bbar)
    for _ in range(neumann_T):
        for i in sites: e[i] += term[i]
        term = {i: sum(cij * term[j] for j, cij in Cbar.get(i, {}).items()) for i in sites}
    tail = (alpha ** neumann_T) * (max(bbar.values()) if bbar else F(0)) / (1 - alpha)
    e = {i: x + tail for i, x in e.items()}
    return dict(alpha=alpha, e=e, bias=[min(F(1), sum(e.get(u, F(0)) for u in q['f'].scope)) for q in C.queries])


def apply_commit(C, rc):
    """apply ONE recorded commit to the current model with the SAME constructive helpers the producer used (no search, no proposer): the record carries every choice"""
    op = rc.get('op')
    if op == 'support': new = _support_apply(C, rc['var'], list(rc['alive'])); C.commit(dict(rc), **new); return
    if op == 'fixed_substitution':
        new, fixed = _fixed_apply(C)
        if new is None: raise ValueError('fixed substitution record on a model without one-state variables')
        C.commit(dict(rc), **new); return
    if op == 'leaf_sumout': new = _leaf_apply(C, rc['var'], rc['factor']); C.commit(dict(rc), **new); return
    if op == 'component_omission': C.commit(dict(rc), **_omission_apply(C, rc['omitted'])); return
    if op in ('exact_quotient_pass', 'approx_quotient'):
        var = rc['var']
        if rc['incident_factors'] != _incident_indices(C.views, var): raise ValueError('quotient record incident set differs from the model (application refuses an unverified factor set)')
        inc = [C.views[i] for i in rc['incident_factors']]; classes = [list(g) for g in rc['classes']]
        if op == 'approx_quotient':
            ap = rc['approx']; slices = {s: [_slice(v, C.cards, var, s) for v in inc] for s in range(C.cards[var])}; sur = []
            for fi, v in enumerate(inc):
                scope = v.scope; rest = [u for u in scope if u != var]; vals = list(v.values)
                for g in ap['groups']:
                    r = g[0]; sl_r = slices[r][fi]; piv_i = next(i for i, x in enumerate(sl_r) if x)
                    for s in g:
                        if s == r: continue
                        c = slices[s][fi][piv_i] / sl_r[piv_i]
                        for ri, xs in enumerate(product(*(range(C.cards[u]) for u in rest))):
                            x = dict(zip(rest, xs)); x[var] = s; i = 0
                            for u in scope: i = i * C.cards[u] + x[u]
                            vals[i] = c * sl_r[ri]
                sur.append(View('table', scope, tuple(vals)))
            saved = C.views; tmp = list(C.views)
            for i, sv in zip(rc['incident_factors'], sur): tmp[i] = sv
            C.views = tmp
            try:
                sig, inc2 = _signatures(C, var); new, rec = _quotient_build(C, var, classes, sig, inc2, ap)
            finally: C.views = saved
            C.commit(dict(rc), bias=[b + F(ap['beta']) for b in C.bias], **new); return
        sig, inc2 = _signatures(C, var)
        if not inc2: sig = {s: [] for s in range(C.cards[var])}
        new, rec = _quotient_build(C, var, classes, sig, inc2, None); C.commit(dict(rc), **new); return
    if op == 'symmetry':
        consts = dict(C.constant_queries)
        for a in rc['actions']:
            for qi, c in a['constants'].items(): consts[int(qi)] = F(c)
        C.commit(dict(rc), constant_queries=consts); return
    if op == 'concentration':
        if _canon_keys(rc.get('bias'), len(C.queries), 'bias') or _canon_keys(rc.get('xstar'), len(C.cards), 'xstar'): raise ValueError('concentration record keys are not canonical (application refuses an unverified map)')
        bias = [C.bias[j] + F(rc['bias'][str(j)]) for j in range(len(C.queries))]          # canonical array: one entry per query, read by its canonical key
        if any(b < 0 for b in bias): raise ValueError('negative accumulated bias')
        C.commit(dict(rc), bias=bias, witness={int(k): v for k, v in rc['xstar'].items()}); return
    if op == 'influence_deletion':
        chosen = set(rc['deleted']); C.commit(dict(rc), views=[v for fi, v in enumerate(C.views) if fi not in chosen], bias=[C.bias[j] + F(rc['bias'][j]) for j in range(len(C.bias))]); return
    if op == 'affine':
        new, rec = _affine_build(C, None, _Ticker(C, None, 'affine'))
        if new is None: raise ValueError('affine record on a model without equations')
        C.commit(dict(rc), **new); return
    raise ValueError('unknown commit op %s' % op)


def replay_journal(task, journal, work, allowance=None, deadline=None, verify=True):
    """the checker's compile replay: start from the evidence restriction, then for every recorded COMMIT verify it on the pre-commit model and apply it; declines are
    checked for shape only (they change nothing). Returns (C, fails, derived). The replayed model's snapshot hash must equal the recorded final_sha256 (checked by the caller)."""
    fails = []; derived = {}
    allowance = allowance if allowance is not None else [(task['epsilon'] / 4 if task['mode'] != 'EXACT_RATIONAL' else F(0))] * len(task['queries'])
    try: C = from_task(task, work); C.allowance = list(allowance)
    except ZeroEvidence: return None, ['journal replay: evidence restriction proves zero'], derived
    if not journal or journal[0].get('kind') != 'evidence': return C, ['journal does not start with the evidence record'], derived
    seq = 0
    for rc in journal[1:]:
        if deadline is not None and time.monotonic() >= deadline: fails.append('UNVERIFIABLE: allowance expired in the journal replay'); break
        k = rc.get('kind')
        if k == 'decline':
            if not rc.get('op') or not rc.get('declined'): fails.append('malformed decline record')
            C.certs = list(C.certs) + [dict(rc)]; continue
        if k != 'commit': fails.append('unknown journal record kind %s' % k); break
        if rc.get('seq') != seq: fails.append('commit sequence numbers are not contiguous (%s at position %d)' % (rc.get('seq'), seq)); break
        if verify:
            m = verify_commit(C, rc, work, allowance)
            if m: fails.append('commit %d (%s): %s' % (seq, rc.get('op'), m)); break
            if rc.get('op') == 'concentration':
                derived['concentration_answers'] = {qi: q['f'].at(C.cards, {int(kk): v for kk, v in rc['xstar'].items()}) for qi, q in enumerate(C.queries)}
                derived['concentration_scopes'] = [tuple(q['f'].scope) for q in C.queries]
        try: apply_commit(C, rc)
        except (ZeroEvidence, ValueError, AssertionError, KeyError, IndexError) as ex: fails.append('commit %d (%s) does not apply: %s' % (seq, rc.get('op'), str(ex)[:100])); break
        if rc.get('witness_after') is not None and ({str(k): v for k, v in C.witness.items()} if C.witness is not None else None) != rc.get('witness_after'): fails.append('commit %d (%s): the recorded transformed witness differs from the one the application derives' % (seq, rc.get('op'))); break
        seq += 1
    return C, fails, derived


# ---------------------------------------------------------------------------------------------------------------- verifiers (independent of the proposers)
def verify_quotient_step(cards_before, views_before, step, work):
    """cross-multiplication check of the proportional identities for a recorded quotient step on the model BEFORE the step: for every incident factor and every class,
    phi(s, y) * pivot(r) == phi(r, y) * pivot(s) for all y; kappa / S recomputed and compared"""
    var = step['var']; classes = step['classes']; inc = [views_before[i] for i in step['incident_factors']]
    if not inc and any(var in v.scope for v in views_before): return 'factor-less quotient recorded for a variable with incident factors'
    if sorted(s for g in classes for s in g) != list(range(cards_before[var])): return 'quotient classes are not a partition of the domain'
    kappa = {}
    for g in classes:
        r = g[0]
        for s in g:
            k = F(1)
            for v in inc:
                sl_s = _slice(v, cards_before, var, s); sl_r = _slice(v, cards_before, var, r); work.entries += 2 * len(sl_s)
                ps = next((x for x in sl_s if x), None); pr = next((x for x in sl_r if x), None)
                if ps is None or pr is None: return 'zero slice in a quotient class'
                for a, b in zip(sl_s, sl_r):
                    if a * pr != b * ps: return 'proportionality fails for var %d states %d/%d' % (var, s, r)
                k *= ps / pr
            kappa[s] = k
    if sorted(step['kappa'].keys()) != sorted(str(s) for s in kappa): return 'kappa keys differ from the domain'
    for s, k in kappa.items():
        if F(step['kappa'][str(s)]) != k: return 'kappa differs for state %d' % s
    for ci, g in enumerate(classes):
        if F(step['S'][ci]) != sum(kappa[s] for s in g): return 'S differs for class %d' % ci
    return None


def verify_affine_record(cards_before, views_before, rec, work):
    """re-derive the local equations of every listed factor (|R| == 2^rank), check Hx = b on every positive row, and that c, B satisfy every equation"""
    pos = {v: i for i, v in enumerate(rec['binary_variables'])}; nb = len(pos)
    if rec['binary_variables'] != [v for v in range(len(cards_before)) if cards_before[v] == 2]: return 'affine binary variable list differs from the model'
    for loc in rec['local']:
        v = views_before[loc['factor']]; le = local_affine(v, cards_before, work)
        if le is None or sorted(le) != sorted(tuple(e) for e in loc['equations']): return 'local affine equations of factor %d do not re-derive' % loc['factor']
        for i, w in enumerate(v.values):
            if w > 0:
                for h, b in le:
                    if bin(h & i).count('1') % 2 != b: return 'positive row violates a local equation'
    for loc in rec['local']:
        v = views_before[loc['factor']]
        for h, b in loc['equations']:
            cbit = 0; brow = 0
            for bit in range(len(v.scope)):
                if (h >> (len(v.scope) - 1 - bit)) & 1:
                    u = v.scope[bit]; cbit ^= int(rec['c'][str(pos[u])]); brow ^= int(rec['B'][str(pos[u])])
            if cbit != b or brow != 0: return 'global parametrization violates a local equation of factor %d' % loc['factor']
    return None
