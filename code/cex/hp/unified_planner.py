"""Unified representation planner v0.1 (brief CLAUDE_UNIFIED_REPRESENTATION_PLANNER.md, 24 Nov 2026): ONE planner in which IDENTITY, a checked EXACT QUOTIENT and checked APPROXIMATE
QUOTIENTS compete to deliver the ORIGINAL requested answers at the requested accuracy for the lowest affordable total cost. Experimental entry point; the accepted v2.13.2 default, the frozen
HP v0.2 executable (coarse_envelope.py) and the executor / kernel are unchanged -- the checked primitives are reused through adapters:
  canonicalize / exact_profile_classes / exact_scales / check_candidate / stage_model / coarse_model / slice_profiles / farthest_split / canonical_classes / unit_scales / centering_scales /
  refine / elimination_order / run_executor / rows_from_witness / publish / epsilon_safe_points / intersect / compact_outward (all from coarse_envelope, byte-identical).
Representations: identity = the canonical model itself (identity decoder, zero representation error, NO profile discovery, NO min/max scan, no dense decoder: a lightweight adapter feeding the
executor the canonical unaries + factors with the scalar once); exact quotient = complete proportional-slice profiles + exact entrywise verification (a quotient with no semantic change ALIASES
identity); approximate quotient = FAST's positive-log profile grouping + unit vs centering by the checked local R + nested refinement, built on the checked exact quotient when it exists, else
directly on identity (identity -> exact -> approximate only; no approximation on an approximation). Lower solve, upper solve and refinement are SEPARATE schedulable actions; control returns
to the planner after each validated result.
Accuracy facts are kept in three layers per candidate: checked representation facts (exact / envelope, decoder, finite R, zero-mass facts, source binding) -> prospective accuracy
(model-bound-promising iff exact or (R - 1) / (R + 1) <= 2 eps; otherwise UNKNOWN, never 'impossible') -> validated original-query intervals (one-solve finite-R bound, two-envelope ratio,
executor error, compaction, epsilon-safe points), intersected per ORIGINAL coordinate across candidates (an empty intersection is a certificate defect).
Cost: an inspectable record per action (work counts x frozen phase rates from PHASE_RATES.json + the 20e6 rows/s kernel rate; the layered route's live-state forecast on the physical order
for memory admission); total cost from request entry and incremental remaining cost are separate; sunk work is never re-charged. Scheduling = the brief's frozen policy (section 6):
identity priced first; among ready exact / promising candidates b = min predicted remaining time (ties: fewer constructions, identity, exact, approx, stable); optional action a eligible iff
D_a + S_a < T_b and q_a = min(2 D_a, T_b / 4, W - min(W, 2 T_b)) >= D_a; else b with an absolute action deadline min(work, now + 2 T_b) when a distinct admitted alternative remains, else the
work deadline; with no affordable b: exploration q_a = min(2 D_a, W / 4) by smallest optimistic completion, else the cheapest untried exact / promising solve on the remaining work deadline,
else finalize. Bounds: 1 exact discovery, 1 FAST discovery, 2 refinements, <= 8 native attempts. Scheduling estimates never enter correctness: every published row is rebuilt exactly."""
import sys, os, json, time, math, argparse, resource
from fractions import Fraction as F
T_PROCESS_START = time.monotonic()
HERE = os.path.dirname(os.path.abspath(__file__)); CODE = os.path.dirname(os.path.dirname(HERE))
if HERE not in sys.path: sys.path.insert(0, HERE)
import coarse_envelope as CE
import cost_model as CM
from coarse_envelope import F, tnow, bits, Refused, Defect, Clock, Budget, checked_mul, fl

VERSION = 'unified-representation-planner-v0.2 (2026-11-24 closeout after the independent review: R1 refinement accounting (old candidates retained with their charges; a new charge is its own live delta, asserted >= 0; ledger identity live = canonical + sum of retained charges), R2 one guarded order + volume pass (vertices / cliques / new fills charged before allocation, polled; optimistic estimates reuse the identity order or the card-1 shortcut, guarded), R3 a zero approximate lower mass with a positive upper mass is a typed no-witness state, never a defect, R4 the diagnostic tail is bounded and the hard deadline is enforced at the API success boundary, R5 an incumbent is cut early only for an alternative that is actually usable in the post-allowance state; v0.1 pilot 1; v0.3 24 Nov second closeout: C1 temporary charges released on construction / estimation refusal and estimator refusals isolated to the optional action, C2 one authoritative final timestamp with late rows suppressed regardless of the outcome label (API and CLI), C3 alternatives must pass the shared admission predicate before they can shorten the incumbent; v0.3.1 24 Nov third closeout: the reviewer-supplied patch C2_FINAL_SAMPLE_AFTER_DIAGNOSTICS applied verbatim -- the per-row width / radius diagnostics are computed BEFORE the authoritative final sample and cleared when publication is suppressed; v0.4 UNIFIED_SCHEDULING_REVISION_1: switches --sched P0|P1 (P1 = in the no-affordable-incumbent branch a constructor may run for W/4 without a D <= q requirement; unknown-quality solves keep D <= min(2D, W/4); allowance anchored to a fresh W sample, capped by the work cutoff, global clock rechecked before dispatch) and --rates R0|R1 (R1 = cost_model.py: nonnegative affine blocks over fixed physical work counts from PHASE_RATES_R1.json); per-action measurements (construction / native host / native kernel / recovery / final) with their features recorded in every result)'
EPS_DEFAULT = F(1, 200); ADMISSION_STOP_S = 3.5; MAX_EXACT_DISCOVERY = 1; MAX_FAST_DISCOVERY = 1; MAX_REFINEMENTS = 2; MAX_NATIVE_ATTEMPTS = 8
KERNEL_ROWS_PER_S = 20e6; MEMORY_SLACK = 1.25; PROCESS_HEADROOM = 64 << 20; FINALIZE_RESERVE_S = 0.05
RATES_PATH = os.path.join(HERE, 'PHASE_RATES.json')
DEFAULT_RATES = dict(frozen=False, note='UNCALIBRATED defaults (replaced by PHASE_RATES.json from calibrate_unified.py before any scored outcome)', setup_s=0.0, canon_per_entry=2e-6, exact_profile_per_axis_entry=4e-6, check_per_entry=3e-6, fast_profile_per_axis_entry=2e-6, distance_per_unit=1e-7, order_per_unit=2e-6, lowering_per_entry=2e-6, kernel_per_row=1.0 / KERNEL_ROWS_PER_S, enclosure_per_state=2e-5, recovery_per_row=1.5e-5, publish_per_row=1.5e-5, build_load_s=0.01, finalize_reserve_s=FINALIZE_RESERVE_S)
def load_rates():
    try: r = json.load(open(RATES_PATH)); return dict(DEFAULT_RATES, **r)
    except Exception: return dict(DEFAULT_RATES)
RATES = load_rates()


# ------------------------------------------------------------------ physical volumes and the cost record
def order_and_volume(cards, scopes, clock, budget, order=None):
    """ONE guarded pass: the deterministic greedy min-product order (identical rule to coarse_envelope.elimination_order: ties -> smallest id; verified by control) OR a supplied order, with
    the physical bucket volumes of that order. Admitted BEFORE allocation: vertex sets, each source clique (k(k-1) directed entries), each fill (only the NEW directed entries); polled at
    entry, per 64 cliques, per 64 candidates and per elimination; the graph charge is released when the graph dies. Returns (order, volume)."""
    clock.poll('at the order / volume pass entry'); B = budget or Budget(1 << 62); n = len(cards); charged = 0
    try:
        return _order_and_volume(cards, scopes, clock, B, order, lambda nb: _charge(B, nb))
    finally: B.release(_CH.pop(id(B), 0))


_CH = {}
def _charge(B, nbytes_what):
    nbytes, what = nbytes_what; c = B.charge(nbytes, what); _CH[id(B)] = _CH.get(id(B), 0) + c; return c


def _order_and_volume(cards, scopes, clock, B, order, charge):
    n = len(cards); charge((n * (216 + 8) + 56, 'primal graph vertex sets')); adj = [set() for _ in range(n)]
    for i, sc in enumerate(scopes):
        k = len(sc); charge((k * (k - 1) * CE.GRAPH_ENTRY_BYTES, 'source clique %d (%d directed entries)' % (i, k * (k - 1))))
        for v in sc: adj[v].update(set(sc) - {v})
        if (i & 63) == 63: clock.poll('in the source cliques')
    alive = set(range(n)); out_order = []; sp = 0; mp = 0; so = 0; mo = 0; step = 0
    while alive:
        if order is None:
            best = None
            for j, v in enumerate(sorted(alive)):
                p_ = cards[v] * math.prod(cards[w] for w in adj[v])
                if best is None or p_ < best[0]: best = (p_, v)
                if (j & 63) == 63: clock.poll('in the candidate scan')
            v = best[1]
        else:
            v = order[step]
            if v not in alive: raise Defect('supplied order repeats or skips a variable')
        nb = adj[v]; out = math.prod(cards[w] for w in nb); prod = cards[v] * out; sp += prod; mp = max(mp, prod); so += out; mo = max(mo, out); m = len(nb); new_entries = 0
        for j, w in enumerate(nb):
            new_entries += len(nb - {w} - adj[w])
            if (j & 63) == 63: clock.poll('in the fill count')
        charge((new_entries * CE.GRAPH_ENTRY_BYTES, 'fill of eliminating %d (%d new directed entries among %d neighbours)' % (v, new_entries, m)))
        for w in nb: adj[w] |= nb - {w}; adj[w].discard(v)
        alive.discard(v); adj[v] = set(); out_order.append(v); step += 1; clock.poll('in the order construction')
    return out_order, dict(sum_product=sp, max_product=mp, sum_output=so, max_output=mo, source_entries=sum(math.prod(cards[v] for v in sc) for sc in scopes) + sum(cards), states=sum(cards), n=n)


def physical_volume(cards, scopes, order, clock=None, budget=None):
    """guarded volume of a SUPPLIED order (delegates to the single guarded pass)"""
    return order_and_volume(cards, scopes, clock or Clock(math.inf, {}), budget, order=order)[1]


def forecast_bytes(vol):
    """the layered route's conservative live-state forecast on the physical order (retained messages + converted sources + 2 x largest output + 2 x largest product) x slack + headroom"""
    payload = 8 * (vol['sum_output'] + vol['source_entries'] + 2 * vol['max_output'] + 2 * vol['max_product']); return int(payload * MEMORY_SLACK) + PROCESS_HEADROOM + 1200 * vol['states']


def est_solve(vol, K_rows):
    """estimated seconds of ONE native solve + recovery on a model with physical volume `vol` delivering K_rows original rows: build/load + lowering + kernel + enclosure + recovery + publish"""
    r = RATES
    parts = dict(build_load=r['build_load_s'], lowering=r['lowering_per_entry'] * vol['source_entries'], kernel=2 * vol['sum_product'] * r['kernel_per_row'], enclosure=r['enclosure_per_state'] * vol['states'], recovery=r['recovery_per_row'] * K_rows, publish=r['publish_per_row'] * K_rows)
    return sum(parts.values()), parts


def est_exact_discovery(M):
    axis_entries = sum(len(sc) * len(vals) for sc, vals in M.factors); entries = sum(len(vals) for _, vals in M.factors); r = RATES
    parts = dict(profiles=r['exact_profile_per_axis_entry'] * axis_entries, check=r['check_per_entry'] * (entries + sum(M.cards)), order=r['order_per_unit'] * (len(M.cards) ** 2 + sum(len(sc) * (len(sc) - 1) for sc, _ in M.factors)))
    return sum(parts.values()), parts, dict(axis_entries=axis_entries, entries=entries)


def est_fast_discovery(M1):
    axis_entries = sum(len(sc) * len(vals) for sc, vals in M1.factors); entries = sum(len(vals) for _, vals in M1.factors); r = RATES
    proflen = [0] * len(M1.cards)
    for sc, vals in M1.factors:
        for ax, v in enumerate(sc): proflen[v] += len(vals) // M1.cards[v]
    dist = sum(M1.cards[v] ** 2 * proflen[v] for v in range(len(M1.cards)))
    parts = dict(profiles=r['fast_profile_per_axis_entry'] * axis_entries, distances=r['distance_per_unit'] * dist, checks=2 * r['check_per_entry'] * (entries + sum(M1.cards)), order=r['order_per_unit'] * (len(M1.cards) ** 2 + sum(len(sc) * (len(sc) - 1) for sc, _ in M1.factors)))
    return sum(parts.values()), parts, dict(axis_entries=axis_entries, distance_units=dist)


# ------------------------------------------------------------------ candidates
class Cand:
    def __init__(self, kind, parent=None):
        self.kind = kind; self.parent = parent; self.stages = []; self.M1 = None; self.Cz = None; self.cards = None; self.scopes = None; self.order = None; self.vol = None; self.exact = kind != 'approx'; self.R = (F(1) if kind != 'approx' else None); self.mixed = False
        self.SL = None; self.SU = None; self.status = dict(lower=None, upper=None); self.constructions = 0; self.fbytes = None; self.failed = set(); self.charged = 0; self.alias_of = None; self.name = kind; self.refinements = 0; self.promising = kind != 'approx'; self.bound_width = (F(0) if kind != 'approx' else None); self.max_bits = 0; self.owns = []; self.shares = {}
    def facts(self):
        return dict(kind=self.kind, name=self.name, exact=self.exact, local_R=fl(self.R), mixed_cells=self.mixed, cards=(list(self.cards) if self.cards else None), states=(sum(self.cards) if self.cards else None), constructions=self.constructions, alias_of=self.alias_of,
                    prospective=dict(model_bound_promising=self.promising, worst_width_bound=(fl(self.bound_width) if self.bound_width is not None else None), quality=('exact' if self.exact else ('promising' if self.promising else 'unknown'))), volume=self.vol, forecast_bytes=self.fbytes, order=self.order, status=dict(self.status), failed=sorted(self.failed), charged_bytes=self.charged, owns=list(self.owns), shares=dict(self.shares), max_bits=self.max_bits)


def cz_bits(Cz):
    return max([bits(x) for L in Cz.L for x in L if x is not None] + [bits(x) for A in Cz.A for x in A] + [0])


def identity_model(M):
    return dict(cards=list(M.cards), evidence={}, factors=[dict(scope=(v,), values=list(M.psi[v])) for v in range(len(M.cards))] + [dict(scope=sc, values=list(vals)) for sc, vals in M.factors])


def rows_identity(M, SL):
    return {(v, a): SL.p[v][a] for v in range(len(M.cards)) for a in range(M.cards[v])}


# ------------------------------------------------------------------ the planner
class Planner:
    def __init__(self, model, budget_s, eps=EPS_DEFAULT, admission_stop_s=ADMISSION_STOP_S, t_start=None, policy='unified', sched='P0', rates='R0'):
        self.t_start = T_PROCESS_START if t_start is None else t_start; self.hard = self.t_start + budget_s; self.adm = self.t_start + min(budget_s, admission_stop_s); self.eps = eps; self.policy = policy
        self.model = model; self.cards_in = list(model['cards']); self.ev_in = dict(model.get('evidence', {})); self.inventory = [(v, a) for v in range(len(self.cards_in)) if v not in self.ev_in for a in range(self.cards_in[v])]
        self.sched = sched; self.rates = rates; self.cm = CM.R1() if rates == 'R1' else None; self.measurements = []; self.mf = None
        self.out = dict(version=VERSION, policy=policy, sched=sched, rates_model=rates, budget_s=budget_s, admission_stop_s=admission_stop_s, epsilon=str(eps), rates=(dict(frozen=RATES.get('frozen'), sha256=RATES.get('sha256')) if rates == 'R0' else dict(frozen=True, sha256=self.cm.sha256, file=os.path.basename(self.cm.path))), phases_s={}, actions=[], candidates=[], decisions=[], measurements=self.measurements, mechanism=dict(native_attempts=0, positive_mass_witness=None), outcome=None, answers=None)
        self.stats = {}; self.clock = Clock(self.adm, self.stats); self.hclock = Clock(self.hard, self.stats); self.budget = Budget(CE.CONSTRUCTOR_BYTES); self.retained = {}; self.M = None; self.cands = []; self.n_exact_disc = 0; self.n_fast_disc = 0; self.n_refine = 0; self.native = 0; self.K_rows = len(self.inventory); self.complete = False; self.failed_global = set(); self.t_mark = self.t_start

    # ---- bookkeeping
    def log_action(self, **kw): kw.setdefault('t_s', round(tnow() - self.t_start, 4)); self.out['actions'].append(kw); return kw
    def W(self): return self.adm - tnow()
    def headroom(self): return CE.USABLE_BYTES - CE.CX.rss_bytes()

    # ---- candidate construction (each a schedulable action with its own Clock = min(allowance, admission))
    def make_identity(self, clock):
        c = Cand('identity'); M = self.M; c.M1 = M; c.cards = list(M.cards); c.scopes = [sc for sc, _ in M.factors]; c.order, c.vol = order_and_volume(c.cards, c.scopes, clock, self.budget); c.fbytes = forecast_bytes(c.vol); c.constructions = 0; c.stages = []; c.owns = []; c.shares = dict(M1='canonical'); c.max_bits = max([bits(x) for ps in M.psi for x in ps] + [bits(x) for _, vals in M.factors for x in vals] + [0]); return c

    def discover_exact(self, clock):
        live0_ = self.budget.live
        try:
            M = self.M; t0 = tnow(); live0 = self.budget.live
            classes1 = CE.exact_profile_classes(M, clock, self.budget); scales1 = CE.exact_scales(M, classes1, clock); Cz1 = CE.check_candidate(M, classes1, scales1, clock, self.budget)
            if not Cz1.exact: raise Defect('the exact profile quotient fails the entrywise identity (L != U)')
            c = Cand('exact'); c.Cz = Cz1; c.stages = [(classes1, Cz1)]; c.M1 = CE.stage_model(M, Cz1); c.cards = list(Cz1.ccards); c.scopes = [sc for sc, _ in c.M1.factors]; c.constructions = 1; c.charged = self.budget.live - live0; c.owns = ['Cz', 'M1', 'classes']; c.max_bits = cz_bits(Cz1)
            if c.charged < 0: raise Defect('negative construction charge for the exact quotient')
            if all(k == card for k, card in zip(Cz1.ccards, M.cards)): c.alias_of = 'identity'; c.name = 'exact_quotient(=identity)'
            else: c.order, c.vol = order_and_volume(c.cards, c.scopes, clock, self.budget); c.fbytes = forecast_bytes(c.vol)
            c.disc_s = tnow() - t0; return c
        except Refused:
            self.budget.release(max(0, self.budget.live - live0_)); raise                           # C1: temporaries of an abandoned construction are released (cumulative stays charged); retained candidates keep their charges

    def discover_fast(self, parent, clock):
        live0_ = self.budget.live
        try:
            M1 = parent.M1; t0 = tnow(); live0 = self.budget.live
            try: prof, why = CE.slice_profiles(M1, clock, self.budget)
            except (ValueError, OverflowError, ZeroDivisionError) as e: prof, why = None, 'profile proposer refused: %s' % str(e)[:80]
            if prof is None: raise Refused('PROPOSER', why)
            self.budget.charge(sum(c * c * 8 for c in M1.cards), 'pairwise distances')
            classes2 = [CE.canonical_classes(CE.farthest_split(prof[v], list(range(M1.cards[v])), clock), M1.cards[v]) if M1.cards[v] > 1 else [0] for v in range(len(M1.cards))]
            unit = CE.unit_scales(M1); Cu = CE.check_candidate(M1, classes2, unit, clock, self.budget)
            try: cen = CE.centering_scales(M1, classes2, clock); Cc = CE.check_candidate(M1, classes2, cen, clock, self.budget); cen_note = None
            except (ValueError, OverflowError, ZeroDivisionError) as e: cen = None; Cc = None; cen_note = 'centering refused: %s' % str(e)[:80]
            pick = 'unit' if (Cc is None or Cc.R is None or (Cu.R is not None and Cu.R <= Cc.R)) else 'centering'
            c = Cand('approx', parent); c.Cz = Cu if pick == 'unit' else Cc; c.scales = unit if pick == 'unit' else cen; c.classes = classes2; c.prof = prof; c.M1 = M1; c.stages = list(parent.stages) + [(classes2, c.Cz)]; c.cards = list(c.Cz.ccards); c.scopes = [sc for sc, _ in M1.factors]
            c.constructions = parent.constructions + 1; c.gauge = dict(unit_R=fl(Cu.R), centering_R=(fl(Cc.R) if Cc is not None else None), selected=pick, centering_refused=cen_note); c.charged = self.budget.live - live0; c.name = 'approx(%s)' % parent.name; c.owns = ['Cz', 'Cz_unit_or_centering_alternative', 'classes', 'scales', 'prof', 'pairwise_distances']; c.shares = dict(M1=parent.name); c.max_bits = cz_bits(c.Cz)
            if c.charged < 0: raise Defect('negative construction charge for the approximate quotient')
            self.set_quality(c); c.order, c.vol = order_and_volume(c.cards, c.scopes, clock, self.budget); c.fbytes = forecast_bytes(c.vol); c.disc_s = tnow() - t0; return c
        except Refused:
            self.budget.release(max(0, self.budget.live - live0_)); raise                           # C1: temporaries of an abandoned construction are released (cumulative stays charged); retained candidates keep their charges

    def refine_cand(self, cand, clock):
        live0_ = self.budget.live
        try:
            t0 = tnow(); live0 = self.budget.live; new, info = CE.refine(cand.M1, cand.Cz, cand.prof, clock)
            if new is None: raise Refused('NO_SPLIT', str(info))
            Cz = CE.check_candidate(cand.M1, new, cand.scales, clock, self.budget); c = Cand('approx', cand.parent); c.Cz = Cz; c.scales = cand.scales; c.classes = new; c.prof = cand.prof; c.M1 = cand.M1; c.stages = list(cand.parent.stages) + [(new, Cz)]; c.cards = list(Cz.ccards); c.scopes = cand.scopes
            c.constructions = cand.constructions + 1; c.refinements = cand.refinements + 1; c.split = info; c.charged = self.budget.live - live0; c.name = 'refine%d(%s)' % (c.refinements, cand.parent.name); c.gauge = cand.gauge; c.owns = ['Cz', 'classes']; c.shares = dict(M1=cand.parent.name, prof=cand.name, scales=cand.name); c.max_bits = cz_bits(Cz)   # R1: the refined-from candidate stays in self.cands with ITS charge (its certificate and solves remain reachable); nothing is released here
            if c.charged < 0: raise Defect('negative construction charge for a refinement')
            self.set_quality(c); c.order, c.vol = order_and_volume(c.cards, c.scopes, clock, self.budget); c.fbytes = forecast_bytes(c.vol); c.disc_s = tnow() - t0; return c
        except Refused:
            self.budget.release(max(0, self.budget.live - live0_)); raise                           # C1: temporaries of an abandoned construction are released (cumulative stays charged); retained candidates keep their charges

    def set_quality(self, c):
        c.exact = c.Cz.exact; c.R = c.Cz.R; c.mixed = c.Cz.mixed
        if c.exact: c.promising = True; c.bound_width = F(0)
        elif c.R is None: c.promising = False; c.bound_width = None
        else: c.bound_width = (c.R - 1) / (c.R + 1); c.promising = c.bound_width <= 2 * self.eps

    # ---- solves (separate actions)
    def exec_model(self, c, side):
        if c.kind == 'identity': return identity_model(self.M)
        return CE.coarse_model(c.M1, c.Cz, side)

    def admitted(self, c):
        """the shared resource / addressability admission of a candidate's native solve (used by solve(), the ready scoring and the alternative test)"""
        return self.native < MAX_NATIVE_ATTEMPTS and c.fbytes is not None and c.fbytes <= self.headroom() and (c.vol or {}).get('max_product', 2 ** 63) <= 2 ** 62

    def solve(self, c, side, deadline, label):
        if self.native >= MAX_NATIVE_ATTEMPTS: raise Refused('ATTEMPTS', 'native attempt cap %d reached' % MAX_NATIVE_ATTEMPTS)
        if c.fbytes is not None and c.fbytes > self.headroom(): raise Refused('FORECAST', 'forecast live state %d B > headroom %d B' % (c.fbytes, self.headroom()))
        self.native += 1; self.out['mechanism']['native_attempts'] = self.native
        return CE.run_executor(self.exec_model(c, side), c.order, self.M.scalar, deadline, self.stats, label)

    def recover(self, c, clock):
        """validated ORIGINAL-coordinate intervals from the candidate's solves (identity: the executor enclosures directly; others: decoder composition + one-solve / two-solve bounds)"""
        if c.kind == 'identity': acc = rows_identity(self.M, c.SL)
        else: acc = CE.rows_from_witness(self.M, c.stages, c.SL, c.SU, c.R, clock)
        if self.retained and set(acc) != set(self.retained): raise Defect('cross-candidate intersection over different original coordinate sets')
        self.retained = CE.intersect(self.retained, acc); rows = CE.publish(self.M, self.retained, self.eps, clock)
        pub = sum(1 for r in rows.values() if r); self.complete = all(r is not None for r in rows.values()); return rows, pub

    # ---- estimates
    def ell_of(self, c):
        """conservative rational-size limbs for a candidate's solve: the canonical model's limbs combined with its certificate's (parent + certificate sizes)"""
        B = self.mf['B_bits'] if self.mf else 1
        return CM.ell_bits(max(B, c.max_bits or 1))
    def solve_features(self, c, side=0, h=None, vol=None, ell=None):
        v = vol or c.vol; hh = len(c.stages) if h is None else h
        U = sum(self.M.cards[x] * c.cards[x] for x in range(len(self.M.cards))) if (side == 1 and c.cards is not None) else 0
        return dict(E_phys=v['source_entries'], S_phys=v['states'], V=2 * v['sum_product'], K=self.K_rows, J=len(self.inventory), h=hh, U=U, ell=(ell if ell is not None else self.ell_of(c)))
    def T_solve(self, c, side=0):
        if self.cm is None: return est_solve(c.vol, self.K_rows)
        return self.cm.solve_cost(self.solve_features(c, side))

    def optimistic_after_exact(self):
        """one-state-per-retained-variable idealization: every bucket product is 1, so the volume needs no graph (n products of 1, n outputs of 1); no allocation"""
        M = self.M; n = len(M.cards); vol = dict(sum_product=n, max_product=1, sum_output=n, max_output=1, source_entries=len(M.factors) + n, states=n, n=n)
        if self.cm is None: return est_solve(vol, self.K_rows)[0]
        return self.cm.solve_cost(dict(E_phys=vol['source_entries'], S_phys=n, V=2 * n, K=self.K_rows, J=len(self.inventory), h=1, U=0, ell=self.mf['ell']))[0]   # prospective: the parent's ell (explicit assumption), one decoder stage
    def optimistic_after_fast(self, parent):
        """<= two coarse states per retained variable on the parent's scopes, along the parent's ALREADY ADMITTED order (bounded structural work reused; guarded by the planner's clock and budget)"""
        M1 = parent.M1; vol = physical_volume([min(2, c) for c in M1.cards], [sc for sc, _ in M1.factors], parent.order, self.clock, self.budget)
        if self.cm is None: return est_solve(vol, self.K_rows)[0]
        return self.cm.solve_cost(dict(E_phys=vol['source_entries'], S_phys=vol['states'], V=2 * vol['sum_product'], K=self.K_rows, J=len(self.inventory), h=len(parent.stages) + 1, U=0, ell=self.ell_of(parent)))[0]   # prospective: the parent's ell, h = parent stages + 1
    def D_exact(self):
        if self.cm is None: return est_exact_discovery(self.M)
        f = self.mf; T, parts = self.cm.construction_cost('exact_construction', f); return T, parts, dict(A_ell=f['A'] * f['ell'], G=f['G'])
    def D_fast(self, parent):
        if self.cm is None: return est_fast_discovery(parent.M1)
        f = CM.model_features(parent.M1, self.clock) if parent.kind != 'identity' else self.mf; f = dict(f, ell=max(f['ell'], self.ell_of(parent))); T, parts = self.cm.construction_cost('fast_construction', f); return T, parts, dict(A_ell=f['A'] * f['ell'], Ddist=f['Ddist'], G=f['G'])
    def D_refine(self, c):
        if self.cm is None:
            D, parts, cnt = est_fast_discovery(c.M1); return parts['checks'] / 2 + parts['order'], dict(check=parts['checks'] / 2, order=parts['order']), cnt
        f = CM.model_features(c.M1, self.clock) if c.parent.kind != 'identity' else self.mf; f = dict(f, ell=max(f['ell'], self.ell_of(c))); T, parts = self.cm.construction_cost('refine_construction', f); return T, parts, dict(A_ell=f['A'] * f['ell'], Ddist=f['Ddist'], G=f['G'])

    # ---- the policy loop
    def run(self):
        out = self.out; mech = out['mechanism']; t0 = tnow()
        try:
            self.hclock.poll('at the planner entry'); self.clock.poll('at the planner entry (admission)')
            self.M = M = CE.canonicalize(self.model, self.clock, self.budget); out['phases_s']['canonicalize'] = tnow() - t0; self.canonical_charge = self.budget.live
            mech['canonical'] = dict(variables=len(M.cards), factors=len(M.factors), entries=sum(len(v) for _, v in M.factors), removed_fixed=len(M.fixed_rows), scalar_bits=bits(M.scalar))
            t2 = tnow(); self.mf = CM.model_features(M, self.clock); out['phases_s']['features'] = tnow() - t2; mech['features'] = dict(self.mf); self.t_mark = tnow()
            if M.zero_mass: mech['positive_mass_witness'] = False; out['Z_enclosure'] = dict(lo='0', hi='0', positive=False); return self.fin('ZERO_EVIDENCE', {}, note='a canonical scalar is exactly zero')
            if not M.cards: mech['positive_mass_witness'] = True; out['Z_enclosure'] = dict(lo=str(M.scalar), hi=str(M.scalar), positive=True); return self.finish_ok({}, 'no retained variables: exact scalar normalizer')
            # step 1: identity priced by the bounded physical-order pass (no discovery)
            t1 = tnow(); ident = self.make_identity(self.clock); self.cands.append(ident); out['phases_s']['price_identity'] = tnow() - t1
            Tid, parts = self.T_solve(ident); self.log_action(action='price', cand='identity', estimate_s=Tid, parts={k: round(v, 5) for k, v in parts.items()}, volume=ident.vol, forecast_bytes=ident.fbytes, actual_s=tnow() - t1, status='PRICED'); self.t_mark = tnow()
            while True:
                self.clock.poll('between actions'); decision = self.decide()
                out['decisions'].append(decision['record'])
                if decision['kind'] == 'finalize': return self.fin(decision['outcome'], CE.publish(M, self.retained, self.eps, self.hclock) if self.retained else {}, note=decision['why'])
                done = self.perform(decision)
                if done: return self.finish_ok(done, decision['record'].get('why', 'complete'))
        except Refused as e:
            if e.kind == 'ZERO_MASS': mech['positive_mass_witness'] = False; out['Z_enclosure'] = dict(lo='0', hi='0', positive=False); return self.fin('ZERO_EVIDENCE', {}, note=str(e.reason)[:200])
            mech['refusal'] = dict(kind=e.kind, reason=str(e.reason)[:300]); rows = {}
            if self.retained and self.M is not None and tnow() < self.hard:
                try: rows = CE.publish(self.M, self.retained, self.eps, self.hclock)
                except (Refused, Defect) as d: rows = {}; mech['late_publish'] = str(d)[:120]
            return self.fin('DEADLINE' if e.kind == 'DEADLINE' and not any(rows.values()) else ('DEADLINE_PARTIAL' if e.kind == 'DEADLINE' else ('PARTIAL' if any(rows.values()) else 'REFUSED')), rows)
        except Defect as e: mech['defect'] = str(e)[:300]; return self.fin('CERTIFICATE_DEFECT', {})
        except (ValueError, OverflowError, ZeroDivisionError) as e: mech['refusal'] = dict(kind='INVALID_OR_NUMERIC', reason=str(e)[:300]); return self.fin('REFUSED', {})

    def ready_exact_or_promising(self):
        """ready candidates whose remaining actions can complete the task with checked accuracy: identity / exact (lower not yet run), promising approx (lower not run, or lower run + upper not run)"""
        out = []
        for c in self.cands:
            if c.alias_of: continue
            if c.kind in ('identity', 'exact') and c.SL is None and 'lower' not in c.failed: out.append((c, 'lower'))
            elif c.kind == 'approx' and c.promising:
                if c.SL is None and 'lower' not in c.failed: out.append((c, 'lower'))
                elif c.SL is not None and c.SU is None and 'upper' not in c.failed and not c.exact: out.append((c, 'upper'))
        return out

    def optional_actions(self):
        """optional constructions and unknown-quality solves with D (remaining cost), S (optimistic additional cost) and `admitted`. An estimator's own resource refusal (MEMORY / BITS / FORECAST)
        makes THAT action unavailable (recorded); it never invalidates the request (C1). A genuinely expired global clock still propagates."""
        acts = []; M = self.M; unavailable = self.out['mechanism'].setdefault('estimation_refusals', [])
        def guarded(name, fn):
            try: return fn()
            except Refused as e:
                if e.kind == 'DEADLINE' and tnow() >= self.adm: raise
                unavailable.append(dict(action=name, kind=e.kind, reason=str(e.reason)[:120], t_s=round(tnow() - self.t_start, 4))); return None
        if self.n_exact_disc < MAX_EXACT_DISCOVERY and not any(c.kind == 'exact' for c in self.cands) and 'exact_discovery' not in self.failed_global:
            r = guarded('discover_exact', lambda: (self.D_exact(), self.optimistic_after_exact()))
            if r is not None: (D, parts, cnt), S = r; acts.append(dict(name='discover_exact', cand=None, D=D, S=S, parts=parts, counts=cnt, admitted=True))
        parent = next((c for c in self.cands if c.kind == 'exact' and not c.alias_of), None) or next((c for c in self.cands if c.kind == 'identity'), None)
        if self.n_fast_disc < MAX_FAST_DISCOVERY and not any(c.kind == 'approx' for c in self.cands) and parent is not None and 'fast_discovery' not in self.failed_global:
            r = guarded('discover_fast', lambda: (self.D_fast(parent), self.optimistic_after_fast(parent)))
            if r is not None: (D, parts, cnt), S = r; acts.append(dict(name='discover_fast', cand=parent, D=D, S=S, parts=parts, counts=cnt, admitted=True))
        for c in self.cands:
            if c.kind != 'approx' or c.alias_of: continue
            adm = self.admitted(c)
            if not c.promising and c.SL is None and 'lower' not in c.failed: D, parts = self.T_solve(c); acts.append(dict(name='solve_lower_unknown', cand=c, D=D, S=0.0, parts=parts, admitted=adm))
            if not c.promising and c.SL is not None and c.SU is None and 'upper' not in c.failed and not c.exact: D, parts = self.T_solve(c, 1); acts.append(dict(name='solve_upper_unknown', cand=c, D=D, S=0.0, parts=parts, admitted=adm))
            if c.refinements < MAX_REFINEMENTS and self.n_refine < MAX_REFINEMENTS and c.SL is not None and 'refine' not in c.failed and not any(x.kind == 'approx' and x.refinements == c.refinements + 1 for x in self.cands):
                r = guarded('refine', lambda: self.D_refine(c))
                if r is not None: D, parts, cnt = r; acts.append(dict(name='refine', cand=c, D=D, S=self.T_solve(c)[0], parts=parts, admitted=True))
        return acts

    def decide(self):
        t_p = tnow()
        try: return self._decide()
        finally: self.t_mark = tnow(); self.out['phases_s']['pricing'] = self.out['phases_s'].get('pricing', 0.0) + (self.t_mark - t_p)

    def _decide(self):
        W = self.W(); ready = self.ready_exact_or_promising(); rec = dict(W_s=round(W, 4), t_s=round(tnow() - self.t_start, 4))
        scored = []
        for c, side in ready:
            T, parts = self.T_solve(c, 0 if side == 'lower' else 1)
            scored.append(dict(cand=c, side=side, T=T, parts=parts, admitted=self.admitted(c), order=(c.constructions, {'identity': 0, 'exact': 1, 'approx': 2}[c.kind], self.cands.index(c))))
        rec['ready'] = [dict(cand=s['cand'].name, side=s['side'], T_s=round(s['T'], 4), admitted=s['admitted'], fits_W=s['T'] <= W) for s in scored]
        fit = [s for s in scored if s['admitted'] and s['T'] <= W]; opts = self.optional_actions() if self.policy == 'unified' else []
        if fit:
            b = min(fit, key=lambda s: (s['T'], s['order'])); Tb = b['T']; reserve = min(W, 2 * Tb); rec.update(b=b['cand'].name, b_side=b['side'], T_b_s=round(Tb, 4), reserved_s=round(reserve, 4))
            elig = []
            for a in opts:
                q = min(2 * a['D'], Tb / 4, max(0.0, W - reserve)); a['q'] = q; a['eligible'] = a.get('admitted', True) and (a['D'] + a['S'] < Tb) and (q >= a['D'])
                if a['eligible']: elig.append(a)
            rec['optional'] = [dict(name=a['name'], cand=(a['cand'].name if a['cand'] is not None else None), D_s=round(a['D'], 4), S_s=round(a['S'], 4), q_s=round(a['q'], 4), eligible=a['eligible'], admitted=a.get('admitted', True)) for a in opts]
            if elig:
                a = min(elig, key=lambda x: (x['D'] + x['S'], x['name'])); rec.update(chosen=a['name'], chosen_cand=(a['cand'].name if a['cand'] is not None else None), allowance_s=round(a['q'], 4), why='optional action under the reserved incumbent (step 4)')
                return dict(kind='optional', act=a, deadline=min(self.adm, tnow() + a['q']), record=rec)
            W_after = max(0.0, W - reserve)                                            # R5: an alternative counts only if it is actually usable AFTER b's allowance: another admitted ready solve (step 5's bounded attempt accepts any admitted untried exact / promising solve) or an optional action eligible under the post-allowance exploration rule D_a <= W_after / 4
            alt_ready = [s['cand'].name + ':' + s['side'] for s in scored if s is not b and s['admitted']]; alt_opt = [a['name'] for a in opts if a.get('admitted', True) and a['D'] <= W_after / 4]; alternatives = alt_ready + alt_opt   # C3: only RESOURCE-ADMITTED alternatives (the same predicate solve() applies) can justify shortening the incumbent
            dl = min(self.adm, tnow() + 2 * Tb) if alternatives else self.adm
            rec.update(chosen='solve_' + b['side'], chosen_cand=b['cand'].name, action_deadline_s=round(dl - self.t_start, 4), W_after_allowance_s=round(W_after, 4), competing_alternative=alternatives[:4], why='execute b (step 6: %s)' % ('reserved 2 T_b, a usable alternative remains' if alternatives else 'no usable alternative after the allowance: remaining work deadline'))
            return dict(kind='solve', cand=b['cand'], side=b['side'], deadline=dl, record=rec)
        # step 5: no affordable exact / promising candidate. P0: every optional action needs D <= q = min(2D, W/4). P1 (revision 1): W is RE-SAMPLED after pricing; a CONSTRUCTOR
        # (discover_exact / discover_fast / refine) gets q = W/4 with NO D <= q requirement (forecasts rank, they do not veto); an unknown-quality native solve keeps P0's rule; the allowance
        # deadline is anchored to the sampling time and capped by the work cutoff; the global clock is rechecked before dispatch. Admission / bits / addressability / caps are never bypassed.
        explor = []; t_sample = tnow(); W1 = self.adm - t_sample if self.sched == 'P1' else W; rec['W_resampled_s'] = round(W1, 4)
        for a in opts:
            if self.sched == 'P1' and a['name'] in ('discover_exact', 'discover_fast', 'refine'): q = W1 / 4; a['q'] = q; a['eligible'] = a.get('admitted', True) and W1 > 0; a['forecast_bypassed'] = bool(a['eligible'] and a['D'] > q)
            else: q = min(2 * a['D'], W1 / 4); a['q'] = q; a['eligible'] = a.get('admitted', True) and a['D'] <= q; a['forecast_bypassed'] = False
            if a['eligible']: explor.append(a)
        rec['optional'] = [dict(name=a['name'], cand=(a['cand'].name if a['cand'] is not None else None), D_s=round(a['D'], 4), S_s=round(a['S'], 4), q_s=round(a['q'], 4), eligible=a['eligible'], admitted=a.get('admitted', True), forecast_bypassed=a.get('forecast_bypassed', False)) for a in opts]
        if explor:
            a = min(explor, key=lambda x: (x['D'] + x['S'], x['name'])); self.clock.poll('before dispatching the exploration action'); rec.update(chosen=a['name'], chosen_cand=(a['cand'].name if a['cand'] is not None else None), allowance_s=round(a['q'], 4), forecast_bypassed=a.get('forecast_bypassed', False), why='exploration with no affordable incumbent (step 5, %s%s)' % (self.sched, '; the time forecast D > W/4 is bypassed for this constructor' if a.get('forecast_bypassed') else ''))
            return dict(kind='optional', act=a, deadline=min(self.adm, t_sample + a['q']), record=rec)
        untried = [s for s in scored if s['admitted']]
        if untried:
            b = min(untried, key=lambda s: (s['T'], s['order'])); rec.update(chosen='solve_' + b['side'], chosen_cand=b['cand'].name, action_deadline_s=round(self.adm - self.t_start, 4), why='bounded attempt of the cheapest admitted exact / promising solve on the remaining work deadline although its time prediction (%.3f s) exceeds W (%.3f s) (step 5)' % (b['T'], W))
            return dict(kind='solve', cand=b['cand'], side=b['side'], deadline=self.adm, record=rec)
        pub = sum(1 for r in (CE.publish(self.M, self.retained, self.eps, self.hclock) if self.retained else {}).values() if r)
        why = 'no admitted action remains (ready: %s; optional: %s)' % ([(s['cand'].name, 'FORECAST' if not s['admitted'] else 'time') for s in scored], [(a['name'], 'does not fit') for a in opts]); rec.update(chosen='finalize', why=why)
        return dict(kind='finalize', outcome=('PARTIAL' if pub else 'REFUSED'), why=why, record=rec)

    def perform(self, d):
        try: return self._perform(d)
        finally: self.t_mark = tnow()

    def _perform(self, d):
        """run the decided action; returns published rows when the task is complete, else None"""
        rec = d['record']; t0 = tnow(); dl = d['deadline']; aclock = Clock(dl, self.stats)
        if d['kind'] == 'solve':
            c, side = d['cand'], d['side']; T = rec['T_b_s'] if 'T_b_s' in rec else None; label = '%s:%s' % (c.name, side)
            try:
                S = self.solve(c, 0 if side == 'lower' else 1, dl, label); t_native = tnow() - t0
                if side == 'lower': c.SL = S
                else: c.SU = S
                if S.zero:
                    c.status[side] = 'ZERO_MASS'
                    if c.exact or side == 'upper': self.out['mechanism']['positive_mass_witness'] = False; self.out['Z_enclosure'] = dict(lo='0', hi='0', positive=False); raise Refused('ZERO_MASS', 'checked zero %s mass certifies zero original mass' % ('upper' if side == 'upper' else 'exact'))
                    c.status[side] = 'LOWER_ZERO_MASS'; self.log_action(action='solve_' + side, cand=c.name, estimate_s=T, actual_s=tnow() - t0, status='LOWER_ZERO_MASS (a valid envelope state; no witness from this candidate)'); return None
                if side == 'upper' and c.SL is not None and c.SL.zero:                 # R3: a valid envelope state (Z_L = 0 < Z <= Z_U): no positive-mass witness from this candidate, nothing to normalize, nothing certified; typed, never a defect
                    c.status[side] = 'UPPER_SOLVED_NO_LOWER_WITNESS'; self.log_action(action='solve_' + side, cand=c.name, estimate_s=T, actual_s=tnow() - t0, kernel_s=S.stats.get('kernel_s'), status='UPPER_SOLVED_NO_LOWER_WITNESS', note='zero lower mass + positive upper mass: no normalized row, no witness; incumbent answers retained'); return None
                self.out['mechanism']['positive_mass_witness'] = True; CE.set_Z(self.out, S.Z_lo if side == 'lower' else c.SL.Z_lo, (S.Z_hi * c.R if (c.R is not None and side == 'lower') else (S.Z_hi if side == 'upper' else None)))
                t_r = tnow(); rows, pub = self.recover(c, aclock); c.status[side] = 'SOLVED'; t_rec = tnow() - t_r; ks = S.stats.get('kernel_s') or 0.0
                fs = self.solve_features(c, 0 if side == 'lower' else 1); self.measurements.append(dict(kind='native', cand=c.name, side=side, features=fs, native_total_s=t_native, kernel_s=ks, host_s=max(0.0, t_native - ks), recovery_s=t_rec, completed=True, host_negative_raw=(t_native - ks < 0)))
                self.log_action(action='solve_' + side, cand=c.name, estimate_s=T, actual_s=tnow() - t0, kernel_s=S.stats.get('kernel_s'), lowering_s=S.stats.get('lowering_s'), enclosure_s=S.stats.get('enclosure_s'), build_s=S.stats.get('build_s'), published_after=pub, K=self.K_rows, max_width=float(max(hi - lo for lo, hi in self.retained.values())), forecast_miss=(T is not None and tnow() - t0 > T), status='COMPLETE' if self.complete else 'PARTIAL', semantic_plan_sha256=(S.certificate or {}).get('semantic_plan_sha256'), kernel_peak_logical_bytes=(S.stats.get('counters') or {}).get('peak_logical_bytes'))
                if self.complete: rec['why'] = 'complete after %s of %s' % (side, c.name); return rows
                return None
            except Refused as e:
                if e.kind == 'ZERO_MASS': raise
                if e.kind == 'DEADLINE' and tnow() >= self.adm: c.status[side] = 'KILLED_GLOBAL_DEADLINE'; self.measurements.append(dict(kind='native', cand=c.name, side=side, features=self.solve_features(c, 0 if side == 'lower' else 1), native_total_s=tnow() - t0, completed=False, censored='GLOBAL_DEADLINE')); self.log_action(action='solve_' + side, cand=c.name, estimate_s=T, actual_s=tnow() - t0, status='KILLED_GLOBAL_DEADLINE', reason=str(e.reason)[:160], forecast_miss=True); raise
                c.failed.add(side); c.status[side] = 'REFUSED_' + e.kind; self.measurements.append(dict(kind='native', cand=c.name, side=side, features=self.solve_features(c, 0 if side == 'lower' else 1), native_total_s=tnow() - t0, completed=False, censored=e.kind)); self.log_action(action='solve_' + side, cand=c.name, estimate_s=T, actual_s=tnow() - t0, status='REFUSED_' + e.kind, reason=str(e.reason)[:160], forecast_miss=(e.kind == 'DEADLINE')); return None
        a = d['act']; name = a['name']
        try:
            if name == 'discover_exact':
                self.n_exact_disc += 1; c = self.discover_exact(aclock); self.cands.append(c); self.measurements.append(dict(kind='exact_construction', features=dict(self.mf), seconds=tnow() - t0, completed=True, alias=bool(c.alias_of))); self.log_action(action=name, estimate_s=a['D'], optimistic_after_s=a['S'], allowance_s=rec.get('allowance_s'), actual_s=tnow() - t0, status='READY' if not c.alias_of else 'ALIAS_OF_IDENTITY', result=c.facts()); self.out['candidates'].append(c.facts())
            elif name == 'discover_fast':
                self.n_fast_disc += 1; c = self.discover_fast(a['cand'], aclock); self.cands.append(c); pf = CM.model_features(a['cand'].M1, aclock) if a['cand'].kind != 'identity' else dict(self.mf); self.measurements.append(dict(kind='fast_construction', parent=a['cand'].name, features=dict(pf, ell=max(pf['ell'], self.ell_of(a['cand']))), seconds=tnow() - t0, completed=True)); self.log_action(action=name, parent=a['cand'].name, estimate_s=a['D'], optimistic_after_s=a['S'], allowance_s=rec.get('allowance_s'), actual_s=tnow() - t0, status='READY', gauge=c.gauge, result=c.facts()); self.out['candidates'].append(c.facts())
            elif name == 'refine':
                self.n_refine += 1; c = self.refine_cand(a['cand'], aclock); self.cands.append(c); pf = CM.model_features(a['cand'].M1, aclock) if a['cand'].parent.kind != 'identity' else dict(self.mf); self.measurements.append(dict(kind='refine_construction', parent=a['cand'].name, features=dict(pf, ell=max(pf['ell'], self.ell_of(a['cand']))), seconds=tnow() - t0, completed=True)); self.log_action(action=name, parent=a['cand'].name, estimate_s=a['D'], optimistic_after_s=a['S'], allowance_s=rec.get('allowance_s'), actual_s=tnow() - t0, status='READY', split=c.split, result=c.facts()); self.out['candidates'].append(c.facts())
            elif name in ('solve_lower_unknown', 'solve_upper_unknown'):
                return self.perform(dict(kind='solve', cand=a['cand'], side=name.split('_')[1], deadline=dl, record=dict(rec, T_b_s=a['D'])))
            return None
        except Refused as e:
            if e.kind == 'ZERO_MASS': raise
            if e.kind == 'DEADLINE' and tnow() >= self.adm: self.log_action(action=name, cand=(a['cand'].name if a['cand'] is not None else None), estimate_s=a['D'], actual_s=tnow() - t0, status='KILLED_GLOBAL_DEADLINE', reason=str(e.reason)[:160]); raise
            kind = e.kind if not (e.kind == 'DEADLINE') else 'ALLOWANCE_EXPIRED'
            if name in ('discover_exact', 'discover_fast'): self.failed_global = set(self.failed_global) | {name.replace('discover_', '') + '_discovery'}
            if name == 'refine': a['cand'].failed.add('refine')
            if name in ('discover_exact', 'discover_fast', 'refine'): self.measurements.append(dict(kind={'discover_exact': 'exact_construction', 'discover_fast': 'fast_construction', 'refine': 'refine_construction'}[name], features=dict(self.mf), seconds=tnow() - t0, completed=False, censored=kind))
            self.log_action(action=name, cand=(a['cand'].name if a['cand'] is not None else None), estimate_s=a['D'], allowance_s=rec.get('allowance_s'), actual_s=tnow() - t0, status='REFUSED_' + kind, reason=str(e.reason)[:160], forecast_miss=(kind == 'ALLOWANCE_EXPIRED')); return None

    # ---- finalization (inventory fixed before canonicalization; HARD clock polled during assembly and before the commit)
    def finish_ok(self, rows, note): self.clock.poll('before success'); self.hclock.poll('before success (hard)'); return self.fin('COMPLETE', rows, note=note)

    def fin(self, oc, rows_canon, note=None):
        """final assembly of every ORIGINAL row. ONE authoritative final timestamp `t_end` decides `wall_s`, `in_process_total_s` and `hard_deadline_respected`; if it lies beyond the hard deadline
        every newly assembled row (fixed / factorless rows included) is suppressed and the outcome is DEADLINE, whatever label the caller passed (C2). Assembly itself is polled per 256 rows."""
        out = self.out; mech = out['mechanism']; out['outcome'] = oc; t_fin = self.t_mark                 # the assembly start = the planner loop's last mark (fin keeps exactly ONE direct clock read: t_end)
        if note: mech['note'] = note
        rows = []; pub = 0; gs = set(); fixed = self.M.fixed_rows if self.M is not None else {}; pos = mech.get('positive_mass_witness')
        try:
            self.hclock.poll('at the final assembly entry')
            for j, (v, a) in enumerate(self.inventory):
                if (j & 255) == 255: self.hclock.poll('in the final assembly')
                if (v, a) in fixed:
                    val, g = fixed[(v, a)]
                    if val is None or not pos: rows.append(dict(var=v, state=a, guarantee='NOT_PUBLISHED')); gs.add('NOT_PUBLISHED'); continue
                    rows.append(dict(var=v, state=a, lo=str(val), hi=str(val), point=str(val), guarantee=g)); pub += 1; gs.add(g); continue
                r = rows_canon.get((v, a)) if rows_canon else None
                if r is None: rows.append(dict(var=v, state=a, guarantee='NOT_PUBLISHED')); gs.add('NOT_PUBLISHED')
                else: rows.append(dict(var=v, state=a, lo=str(r['lo']), hi=str(r['hi']), point=str(r['point']), guarantee=r['guarantee'])); pub += 1; gs.add(r['guarantee'])
        except Refused as e: mech['late_assembly'] = str(e.reason)[:120]; rows = []; pub = 0; gs = set()
        out['candidates'] = [c.facts() for c in self.cands]; mech.update(constructor_budget_peak_bytes=self.budget.peak, constructor_budget_cumulative_bytes=self.budget.cumulative, constructor_live_at_end_bytes=self.budget.live, constructor_live_ledger_identity=(self.budget.live == getattr(self, 'canonical_charge', 0) + sum(c.charged for c in self.cands)), polls=self.clock.polls + self.hclock.polls, native_attempts=self.native, exact_discoveries=self.n_exact_disc, fast_discoveries=self.n_fast_disc, refinements=self.n_refine,
                    rational_bit_peak=max([c.max_bits for c in self.cands] + [bits(self.M.scalar) if self.M else 0]), representations_solved=[c.name for c in self.cands if c.SL is not None])
        out['peak_rss_bytes'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # Finish per-row diagnostics before the authoritative deadline sample.
        ws = [F(r['hi']) - F(r['lo']) for r in rows if r['guarantee'] != 'NOT_PUBLISHED']; out['max_width'] = float(max(ws)) if ws else None
        rad = [max(F(r['point']) - F(r['lo']), F(r['hi']) - F(r['point'])) for r in rows if r['guarantee'] != 'NOT_PUBLISHED']; out['max_point_radius'] = float(max(rad)) if rad else None
        t_end = tnow()                                                                       # the ONE authoritative final sample
        out['phases_s']['final_assembly'] = t_end - t_fin; out['final_J'] = len(self.inventory); acc = sum(x.get('actual_s') or 0 for x in out['actions'] if x.get('action') != 'price') + sum(v for k, v in out['phases_s'].items() if k in ('canonicalize', 'features', 'price_identity', 'pricing', 'final_assembly')); out['unassigned_residual_s'] = (t_end - self.t_start) - acc
        out['wall_s'] = t_end - self.t_start; out['in_process_total_s'] = t_end - T_PROCESS_START; out['hard_deadline_respected'] = t_end <= self.hard
        if not out['hard_deadline_respected'] or not rows:
            if pub or not rows: mech.setdefault('late_assembly', 'hard deadline expired before the final sample' if not out['hard_deadline_respected'] else mech.get('late_assembly'))
            if not out['hard_deadline_respected'] and pub: mech['suppressed_late_rows'] = pub
            rows = [dict(var=v, state=a, guarantee='NOT_PUBLISHED') for v, a in self.inventory]; pub = 0; gs = {'NOT_PUBLISHED'}
            out['max_width'] = None; out['max_point_radius'] = None
            if not out['hard_deadline_respected']: out['outcome'] = oc = 'DEADLINE'
        out['answers'] = rows; out['published'] = pub; out['K'] = len(rows); out['guarantee'] = 'EXACT' if gs <= {'EXACT'} else ('DETERMINISTIC' if gs <= {'EXACT', 'DETERMINISTIC'} else 'PARTIAL')
        if out['outcome'] == 'COMPLETE' and pub < len(rows): out['outcome'] = 'PARTIAL'
        if out['outcome'] == 'REFUSED' and pub > 0: out['outcome'] = 'PARTIAL'
        return out

def plan_and_solve(model, budget_s, policy='unified', eps=EPS_DEFAULT, admission_stop_s=ADMISSION_STOP_S, t_start=None, sched='P0', rates='R0'):
    return Planner(model, budget_s, eps=eps, admission_stop_s=admission_stop_s, t_start=t_start, policy=policy, sched=sched, rates=rates).run()


def write_result(out, path, budget_s, t_process_start=None):
    """serialize to a temporary file, enforce the hard deadline before the commit (a late commit publishes nothing, whatever the outcome label), record the output time"""
    t_process_start = T_PROCESS_START if t_process_start is None else t_process_start; t_w = tnow(); tmp = path + '.tmp'; os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True); json.dump(out, open(tmp, 'w'), indent=1, default=str)
    if tnow() > t_process_start + budget_s and (out.get('published') or 0) > 0:
        out['mechanism']['late_commit'] = dict(outcome_before=out['outcome'], published_before=out.get('published')); out['outcome'] = 'DEADLINE'; out['answers'] = [dict(var=r['var'], state=r['state'], guarantee='NOT_PUBLISHED') for r in (out.get('answers') or [])]; out['published'] = 0; out['guarantee'] = 'PARTIAL'; out['max_width'] = None; out['max_point_radius'] = None; json.dump(out, open(tmp, 'w'), indent=1, default=str)
    out['hard_deadline_respected_at_commit'] = tnow() <= t_process_start + budget_s; out['phases_s']['output'] = tnow() - t_w; os.replace(tmp, path); return out


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--input', required=True); ap.add_argument('--output', required=True); ap.add_argument('--budget', type=float, default=3.85, help='HARD worker deadline from process start'); ap.add_argument('--admission-stop', type=float, default=ADMISSION_STOP_S)
    ap.add_argument('--policy', default='unified', choices=['unified', 'identity']); ap.add_argument('--epsilon', default='1/200'); ap.add_argument('--sched', default='P0', choices=['P0', 'P1']); ap.add_argument('--rates', default='R0', choices=['R0', 'R1']); a = ap.parse_args()
    sys.path.insert(0, os.path.join(CODE, 'cex', 'newarm')); import core as CORE
    t0 = tnow(); model, binding = CORE.read_uai(a.input); tread = tnow() - t0
    out = plan_and_solve(model, a.budget, policy=a.policy, eps=F(a.epsilon), admission_stop_s=a.admission_stop, sched=a.sched, rates=a.rates); out['phases_s']['read'] = tread; out['binding'] = binding; out['input'] = os.path.abspath(a.input); out['argv'] = sys.argv[1:]; out['process_start_to_read_s'] = t0 - T_PROCESS_START
    write_result(out, a.output, a.budget)
    print(json.dumps(dict(outcome=out['outcome'], guarantee=out.get('guarantee'), published=out.get('published'), K=out.get('K'), wall_s=round(out['wall_s'], 3), native=out['mechanism'].get('native_attempts'), actions=[(x.get('action'), x.get('cand'), x.get('status')) for x in out['actions']], refusal=out['mechanism'].get('refusal'), defect=out['mechanism'].get('defect')), default=str))


if __name__ == '__main__': main()
