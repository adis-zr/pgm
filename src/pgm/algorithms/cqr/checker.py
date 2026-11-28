"""INDEPENDENT END-TO-END CHECKER of a CQR worker output (the gate's validator for the CQR arms). Trust boundary: the ORIGINAL task bytes (shared reader), the worker JSON.
It RE-DERIVES, never trusts:
  1. task binding (sha256 of model / .evid / .query.json; task identity); mode / epsilon / delta against the manifest task; arm's recorded operator set == registry arm;
  2. the compiler chain: starting from the evidence-restricted original task it REPLAYS every recorded certificate step with the independent verifiers (quotient
     proportionality by cross-multiplication + kappa / S; affine local equations re-derived; symmetry action re-verified; influence / concentration / approximate-quotient
     bias re-derived from the recorded operands) and reproduces the final compiled model byte-for-byte (final_sha256);
  3. the frontier: replays every split / close / carve / prune event from the root on the compiled model; every closed cell is re-enumerated exactly; resolved totals match;
  4. every recorded draw: the launch law (cell cap E_C, N_C, U or E) is recomputed from the replayed frontier AT THAT TIME, the drawn point's weight and query values are
     re-evaluated, the statistic recomputed; the final H / G / V of each stream and the outward boundary are recomputed; the risk allocation is checked;
  5. publication: deterministic bounds re-derived from the final frontier (roots), positive mass / denominators, feasibility (tau = eps - bias - rounding), the
     published point inside the bounds, the legacy rows (if present) equal the per-query answers, outward decimals contain the exact point;
  6. EXACT publications: the reference result re-enumerated by the independent oracle when the free space is <= 2^22 assignments (else UNVERIFIABLE_REFERENCE_SIZE);
  7. zero proofs re-derived (compiler proof replayed; frontier closed with zero mass; reference enumeration re-run under the cap).
Returns a list of failure strings (empty = accepted). Deadline-aware (UNVERIFIABLE when the allowance expires)."""
import os, sys, json, time, hashlib, random
from fractions import Fraction as F
import sys as _sys; _sys.set_int_max_str_digits(0)
from itertools import product
from math import prod
from . import task as TK; from . import compiler as CP; from . import frontier as FR; from . import numerics as NM; from . import oracle as OR; from . import solve as SV; from . import structural as ST
from .views import View
from .task import Work

CHECKER_VERSION = 'cqr-checker-v1.10 (2026-11-19, repair-2 review Z-O1 / Z-O2: zero-record fields (bias / stream counters / epochs / claimed mass) validated by type before any conversion (malformed = typed refusal, never an exception); interior deadline checks inside the zero-slice scan, inside every replayed frontier event (close / cell bounds through the Frontier service hook) and after the independent zero routes (a late zero verification is UNVERIFIABLE, never an acceptance); v1.9 2026-11-18, A1 review CQR-A1-01: frontier_closed_zero_mass proofs verified by journal + partition replay with zero-mass TRANSFER to the original model (exact zero-preserving operators / original-factor zero slice / bounded elimination; never a producer mass field); reference_enumeration proofs beyond the enumeration cap fall back to the same independent short routes before UNVERIFIABLE; v1.8 2026-11-18, structured-repair review CQR-S2-01: presentation labels validated by their DENOTATION (task.validate_output_metadata) for every query and route -- the structural branch no longer requires the literal singleton spelling; legacy-row placement table-derived; v1.7 2026-11-17, structured review CQR-S1-01..03: singleton correspondence derived from each query TABLE (output metadata must agree); the structural flag and route eligibility bound to the registered arm; structural attribution built from the FACTS of the re-execution with kernel digests verified against the verifier\'s own loaded kernels and producer observations labelled; the structural_reduced route (reduction re-derived, decoder + reduced model compared, rows lifted); v1.6: structural routes (structural_original / structural_compiled) verified by bounded re-execution of the recorded executor route on the bound model (rows must reproduce exactly; kernel enclosures trusted at this boundary, kernel provenance bound to the frozen identity by the gate), composed per query and bias-widened on the compiled representation; every mutation class refused; v1.5: every recorded frontier / stream event is validated against its schema (object with a known op; required fields present; rational operands parsable and finite) before replay -- malformed events are typed refusals of the direct API, never tracebacks; the certificate frontier order is validated as a permutation and bound to the registered canonical producer policy; ratio prior bound to the replayed root frontier; tolerances compared as exact rationals)'
ORACLE_CAP = 1 << 22


class Unverifiable(Exception): pass


def _F(x): return x if isinstance(x, F) else F(str(x))


# the recorded-event schema (ninth review, nonblocking correction 1): op -> required fields; a rational operand must parse as a finite Fraction (a zero denominator is malformed)
EVENT_SCHEMA = dict(split=('cell', 'children'), close=('cell',), carve=('cell', 'x'), ratio_draw=('cell', 'U', 'x', 'A', 'a', 'd', 'b'), epoch_start=('epoch', 'delta_e', 'candidate', 'E_star'),
                    epoch_retired=('epoch',), epoch_E_zero=('epoch',), signed_draw=('epoch', 'cell', 'E', 'p', 'd', 'x'), ratio_stream_stopped=(), prune_zero=(), optional_cancelled=(), optional_operator_failed=())
EVENT_RATIONALS = dict(ratio_draw=('U', 'A', 'b'), epoch_start=('delta_e', 'E_star'), signed_draw=('E', 'p'))
EVENT_RATIONAL_LISTS = dict(ratio_draw=('a', 'd'), epoch_start=('candidate',), signed_draw=('d',))


def _event_problem(ev):
    """None if the recorded event is well-formed (an object with a known op, its required fields present, its rational operands parsable); else the reason"""
    if not isinstance(ev, dict): return 'event is not an object (%s)' % type(ev).__name__
    op = ev.get('op')
    if op not in EVENT_SCHEMA: return 'unknown event op %r' % (op,)
    missing = [k for k in EVENT_SCHEMA[op] if k not in ev or ev[k] is None]
    if missing: return 'event %s lacks %s' % (op, missing)
    if 'cell' in EVENT_SCHEMA[op] and (isinstance(ev['cell'], bool) or not isinstance(ev['cell'], int)): return 'event %s: cell id is not an integer' % op
    if 'x' in EVENT_SCHEMA[op]:
        x = ev['x']
        if not isinstance(x, dict): return 'event %s: point is not an object' % op
        try:
            if any(not isinstance(v, int) or isinstance(v, bool) for v in x.values()) or any(int(k) < 0 for k in x): return 'event %s: point states must be integers' % op
        except (ValueError, TypeError): return 'event %s: point keys are not variable indices' % op
    for k in EVENT_RATIONALS.get(op, ()):
        try: _F(ev[k])
        except (ValueError, ZeroDivisionError, TypeError): return 'event %s: operand %s = %r is not a finite rational' % (op, k, ev[k])
    for k in EVENT_RATIONAL_LISTS.get(op, ()):
        if not isinstance(ev[k], (list, tuple)): return 'event %s: %s is not a list' % (op, k)
        try: [_F(v) for v in ev[k]]
        except (ValueError, ZeroDivisionError, TypeError): return 'event %s: %s holds a non-rational' % (op, k)
    if op == 'split' and (not isinstance(ev['children'], list) or any(isinstance(c, bool) or not isinstance(c, int) for c in ev['children'])): return 'event split: children must be a list of integers'
    if op in ('epoch_start', 'epoch_retired', 'epoch_E_zero', 'signed_draw') and (isinstance(ev['epoch'], bool) or not isinstance(ev['epoch'], int)): return 'event %s: epoch id is not an integer' % op
    return None


EXACT_ROUTES = ('exact_reference', 'exact_frontier_closure', 'exact_zero_dimensional', 'normalizer_exact_reference', 'normalizer_exact_frontier_closure', 'normalizer_exact_zero_dimensional')
DET_ROUTES = ('deterministic_frontier', 'deterministic_frontier_closure', 'deterministic_zero_dimensional', 'deterministic_concentration', 'deterministic_signed_residual_E_zero', 'normalizer_deterministic_frontier', 'structural_original', 'structural_reduced', 'structural_compiled')
STRUCTURAL_ROUTES = ('structural_original', 'structural_reduced', 'structural_compiled')
PAC_ROUTES = ('pac_ratio_intersected_with_deterministic', 'pac_signed_residual_validation', 'normalizer_pac_ratio_intersected_with_deterministic')



# ---- zero-evidence proofs (CQR-A1-01): operators whose commit preserves zero mass EXACTLY (Z_original = positive scalars x Z_compiled): evidence restriction, dead-state removal, substitution of
# one-state variables (zero constants raise ZeroEvidence at compile time, positive ones are recorded scalars), exact leaf marginalization, omission of a component whose mass is PROVED positive,
# the exact quotient (proportional classes merged with their exact kappa). Every other operator (approximate quotient, concentration, influence deletion, symmetry, affine) is NOT assumed to
# preserve zero mass: the transfer then needs an independent witness (a zero slice of an original factor under the evidence) or the bounded elimination oracle.
ZERO_PRESERVING_EXACT_OPS = frozenset(('evidence', 'support_fixpoint', 'support', 'fixed_substitution', 'leaf_sumout', 'component_omission', 'exact_quotient_pass'))
def _scalar_positive(sc):
    """a recorded scalar is positive: a numeric value > 0, or the symbolic positive omitted-component mass (its positivity is what component_omission proves)"""
    if not isinstance(sc, dict): return False
    if sc.get('kind') == 'omitted_component_mass': return True
    try: return F(str(sc.get('value'))) > 0
    except (ValueError, ZeroDivisionError, TypeError): return False


def zero_slice_witness(model, work, deadline=None):
    """INDEPENDENT short proof of Z = 0 on the ORIGINAL model: an original factor every one of whose evidence-consistent entries is exactly 0 (then every evidence-consistent assignment
    has a zero factor and Z = 0). Reads every entry of every factor at most once (charged to `work`); returns dict(factor, scope, evidence_consistent_entries) or None (no such factor)."""
    from itertools import product
    cards = model['cards']; ev = model.get('evidence', {})
    for fi, f in enumerate(model['factors']):
        if deadline is not None and time.monotonic() >= deadline: return None
        sc = tuple(f['scope']); n_cons = 0; all_zero = True
        for xs, wv in zip(product(*(range(cards[v]) for v in sc)), f['values']):
            work.entries += 1
            if deadline is not None and (work.entries & 4095) == 0 and time.monotonic() >= deadline: return None       # interior deadline check (repair-2 review Z-O2): a large factor scan observes the allowance
            if any(v in ev and ev[v] != x for v, x in zip(sc, xs)): continue
            n_cons += 1
            if wv != 0: all_zero = False; break
        if all_zero and n_cons > 0: return dict(factor=fi, scope=list(sc), evidence_consistent_entries=n_cons)
    return None


class _ReplayDeadline(Exception): pass


def _zero_record_problem(cert, zp):
    """TYPED validation of the zero-record fields the frontier zero branch converts (repair-2 review Z-O1): returns None or the reason. bias: list of rationals (parsable, finite,
    nonzero denominator); ratio_stream: absent or an object whose `t` is a nonnegative int; epochs: absent or a list of objects whose `t` is a nonnegative int; zero_evidence_proof:
    resolved_mass a rational string and open_cells a nonnegative int. Nothing is converted before this validation, so a malformed record is a refusal, never an exception."""
    def _rat(v):
        try: F(str(v)); return True
        except (ValueError, ZeroDivisionError, TypeError): return False
    def _nn_int(v): return isinstance(v, int) and not isinstance(v, bool) and v >= 0
    b = cert.get('bias')
    if b is not None and (not isinstance(b, list) or any(not _rat(x) for x in b)): return 'bias ledger is not a list of rationals'
    rs = cert.get('ratio_stream')
    if rs is not None and (not isinstance(rs, dict) or not _nn_int(rs.get('t', 0))): return 'ratio_stream record is not an object with an integer draw count'
    ep = cert.get('epochs')
    if ep is not None and (not isinstance(ep, list) or any(not isinstance(e, dict) or not _nn_int(e.get('t', 0)) for e in ep)): return 'epochs record is not a list of objects with integer draw counts'
    if not isinstance(zp, dict) or not _rat(zp.get('resolved_mass')) or not _nn_int(zp.get('open_cells')): return 'zero_evidence_proof lacks a rational resolved_mass / integer open_cells'
    return None


def _attribution(route, cls, exact_route, C, cert, info):
    """the report-facing attribution DERIVED from verified information (second review R6): route, proof class, exactness, the committed operators of the journal, the compiled
    bias ledger, and the interpretation of that ledger for the ORIGINAL answers: on an exact-reference route the compiled surrogate was SUPERSEDED (its bias is a diagnostic
    of unused optional work, never an error applied to the published exact answers); on a compiled route the bias widens the published original intervals"""
    bias = [str(b) for b in C.bias] if C is not None else None
    if route in ('exact_reference', 'normalizer_exact_reference'): interp = 'exact reference: zero error on the original answers; the compiled ledger (if any) is a superseded-surrogate diagnostic'
    elif route == 'structural_original': interp = 'structural route on the ORIGINAL model: deterministic kernel enclosures (trusted at the bounded re-execution boundary), no compiler bias'
    elif route == 'structural_compiled': interp = 'structural route on the COMPILED model: deterministic kernel enclosures of the compiled singleton rows, composed per query and widened by the compiler bias ledger'
    elif exact_route: interp = 'exact closure: zero bias (the route requires every ledger entry to be zero)'
    else: interp = 'compiled route: the ledger widens every published original interval'
    return dict(route=route, guarantee=cls, exact=exact_route, commits=info.get('commits') or [], declines=info.get('declines') or [], compiled_bias=bias, structural=info.get('structural'),
                bias_applied_to_original_answers=(bias if (bias is not None and not exact_route and route not in ('exact_reference', 'normalizer_exact_reference')) else (['0'] * len(bias) if bias is not None else None)),
                bias_interpretation=interp, optional_cancelled=(cert or {}).get('optional_cancelled'), compile_outcome=info.get('compile_outcome'))

def guarantee_class_of_route(route):
    """the proof class a route can establish (review CQR-04): exact routes and deterministic routes => DETERMINISTIC (exact routes additionally exact); statistical routes => PAC"""
    if route in EXACT_ROUTES: return 'DETERMINISTIC', True
    if route in DET_ROUTES: return 'DETERMINISTIC', False
    if route in PAC_ROUTES: return 'PAC', False
    return None, False


def mode_permits(mode, route):
    cls, exact = guarantee_class_of_route(route)
    if cls is None: return False
    if mode == 'EXACT_RATIONAL': return exact
    if mode == 'DETERMINISTIC_EPS': return cls == 'DETERMINISTIC'
    return True


def check_worker_output(model_path, w, manifest_task=None, arm=None, deadline=None):
    """main entry; returns (failures, info). The AUTHORITATIVE task is the input file (+ optional query spec) and, when given, the manifest's frozen declaration; the worker's
    own mode / epsilon / delta / guarantee labels are checked AGAINST it, never used to define it (review CQR-04)."""
    fails = []; info = {}; work = Work()
    def fail(m): fails.append(m)
    def late(): return deadline is not None and time.monotonic() >= deadline
    # ---------------- 1. binding and requested semantics
    try: task = TK.load_task(model_path)
    except Exception as ex: return ['task not readable: %s' % str(ex)[:220]], info
    if manifest_task:
        for k in ('epsilon', 'delta'):
            if k in manifest_task:
                # the frozen declaration keeps the source spelling (0.005, 2/400, 1/200 are the same rational); it is compared by EXACT rational value with the same parser
                # semantics as the authoritative task (seventh review, CQR-R6-03); the file bytes themselves are bound separately through the task binding hashes
                if str(manifest_task[k]) == str(task[k]): continue
                try: mv = F(str(manifest_task[k]))
                except (ValueError, ZeroDivisionError, TypeError): fail('the frozen manifest task %s (%s) is not a rational' % (k, manifest_task[k])); continue
                if mv != task[k]: fail('the frozen manifest task %s (%s) differs from the input file (%s)' % (k, manifest_task[k], task[k]))
        if manifest_task.get('mode') and manifest_task['mode'] != task['mode']: fail('the frozen manifest task mode %s differs from the input file mode %s' % (manifest_task['mode'], task['mode']))
        if 'normalizer_task' in manifest_task and bool(manifest_task['normalizer_task']) != bool((task.get('query_spec') or {}).get('normalizer_task')): fail('the frozen manifest normalizer flag differs from the input file')
    # every presentation label (constructor-built or explicit) must denote the function of its own table (CQR-S1-01 / S2-01): validated by denotation, never by one literal spelling
    for j, q in enumerate(task['queries']):
        try: TK.validate_output_metadata(q, task['model']['cards'])
        except ValueError as ex: fail('query %d: %s' % (j, str(ex)[:200]))
    if w.get('binding') != task['binding']: fail('worker binding differs from the files on disk')
    if w.get('task_identity') != TK.task_identity(task): fail('task identity differs from the re-derived identity')
    cert = w.get('certificate') or {}
    if cert.get('certificate_version') != 'cqr-certificate-v1': fail('unknown certificate version %s' % cert.get('certificate_version')); return fails, info
    if cert.get('diagnostic'): fail('a DIAGNOSTIC run (%s) is never a production publication' % cert.get('diagnostic')); return fails, info
    if cert.get('fault_injected') or w.get('fault_injected'): fail('a FAULT-INJECTION run (%s) is never a production publication' % (cert.get('fault_injected') or w.get('fault_injected'))); return fails, info
    mode = task['mode']; eps = task['epsilon']; delta = task['delta']; normalizer = bool((task.get('query_spec') or {}).get('normalizer_task'))
    if w.get('mode') != mode: fail('worker mode %s differs from the authoritative task mode %s' % (w.get('mode'), mode))
    if cert.get('mode') != mode: fail('certificate mode %s differs from the authoritative task mode %s' % (cert.get('mode'), mode))
    def _same(v, ref):
        try: return F(str(v)) == ref
        except (ValueError, ZeroDivisionError, TypeError): return False
    if not _same(cert.get('epsilon'), eps) or not _same(w.get('epsilon'), eps): fail('epsilon differs from the authoritative task')
    if not _same(cert.get('delta'), delta) or not _same(w.get('delta'), delta): fail('delta differs from the authoritative task')
    if bool(cert.get('normalizer_task')) != normalizer: fail('certificate normalizer flag differs from the task')
    if arm is not None:
        if cert.get('arm') != arm or w.get('arm') != arm: fail('arm differs from the planned arm')
        spec = SV.ARMS.get(arm)
        if spec is None: fail('unknown arm'); return fails, info
        eff = CP.effective_operators(spec['enabled'], task)
        if sorted(cert.get('arm_operators') or []) != sorted(spec['enabled']): fail('recorded arm operator set differs from the registered arm')
        if sorted(cert.get('enabled_operators') or []) != sorted(eff): fail('recorded task-effective operator set differs from the registered arm policy for this task')
        if bool(cert.get('structural_backend')) != bool(spec.get('structural')): fail('recorded structural_backend flag %s differs from the registered arm %s (structural backend %s)' % (cert.get('structural_backend'), arm, bool(spec.get('structural'))))
        if (cert.get('publication') or {}).get('route') in STRUCTURAL_ROUTES and not spec.get('structural'): fail('structural route %s published under arm %s whose registered structural backend is DISABLED' % ((cert.get('publication') or {}).get('route'), arm))
        if bool(cert.get('signed_stream')) != (spec['signed_stream'] and not normalizer) or bool(cert.get('query_directed_refinement')) != (spec['query_directed_refinement'] and not normalizer): fail('recorded stream flags differ from the registered arm policy for this task')
    if (cert.get('publication') or {}).get('route') in STRUCTURAL_ROUTES and not (SV.ARMS.get(cert.get('arm')) or {}).get('structural'): fail('structural route under an arm (%s) without the structural backend' % cert.get('arm'))
    enabled_eff = set(cert.get('enabled_operators') or [])
    # ---------------- zero proofs
    if w.get('outcome') == 'PROVED_ZERO_EVIDENCE':
        if w.get('guarantee_type') != 'DETERMINISTIC': fail('zero-evidence proof must carry the DETERMINISTIC class')
        zp = w.get('zero_evidence_proof') or {}
        if zp.get('kind') == 'compiler':
            try: CP.compile_task(task, enabled=enabled_eff, work=work); fail('compiler zero proof does not re-derive (compile succeeded)')
            except CP.ZeroEvidence as z:
                if z.proof.get('kind') != (zp.get('proof') or {}).get('kind'): fail('compiler zero proof kind differs (%s vs %s)' % (z.proof.get('kind'), (zp.get('proof') or {}).get('kind')))
        elif zp.get('kind') == 'frontier_closed_zero_mass':
            # CQR-A1-01 (review of 18 Nov 2026): the producer's proof is the RECORDED compile journal + partition events whose replay leaves NO open cell and ZERO resolved mass.
            # It is verified ROUTE-FAITHFULLY: (1) the journal replays exactly (policy, commits, final snapshot digest, ledger) as for any compiled publication; (2) the recorded
            # canonical partition events replay on the replayed compiled model to an empty frontier with resolved mass 0 and upper mass 0 (frontier.py prunes a child only when its
            # independently recomputed envelope B is 0); (3) ZERO-MASS TRANSFER to the ORIGINAL model is established, never assumed: either every committed operator is in the
            # declared exact zero-preserving set with a zero bias ledger (Z_original = positive scalars x Z_compiled), or an INDEPENDENT original-factor zero slice under the
            # evidence is found (a factor all of whose evidence-consistent entries are 0), or the bounded independent elimination oracle gives Z = 0; a producer-claimed mass field is
            # never trusted; an unfinished verification is UNVERIFIABLE (never an acceptance); Z > 0 from the independent oracle is a CONTRADICTION (hard refusal).
            comp = cert.get('compile')
            if not isinstance(comp, dict) or not isinstance(comp.get('certificates'), list): fail('frontier zero proof without a compile journal'); return fails, info
            C, jf, _d = CP.replay_journal(task, comp['certificates'], work, deadline=deadline)
            for m_ in jf: fail(('UNVERIFIABLE: ' if 'UNVERIFIABLE' in m_ else 'zero proof journal replay: ') + m_)
            if C is None or jf: return fails, info
            _opname = {'support': 'support_fixpoint'}; journal = comp['certificates']
            bad_ops = sorted({c_.get('op') for c_ in journal if c_.get('kind') == 'commit' and _opname.get(c_.get('op'), c_.get('op')) not in enabled_eff and c_.get('op') != 'evidence'})
            if bad_ops: fail('zero proof journal commits by operators outside the task-effective policy: %s' % bad_ops); return fails, info
            snap_ = C.snapshot_json(); sha_ = hashlib.sha256(json.dumps(snap_, sort_keys=True, default=str).encode()).hexdigest()
            if sha_ != comp.get('final_sha256'): fail('zero proof: compiled model does not replay from the journal (final_sha256 %s vs %s)' % (sha_[:12], str(comp.get('final_sha256'))[:12])); return fails, info
            zb = _zero_record_problem(cert, zp)                              # the TYPED data boundary of the zero record (repair-2 review Z-O1): bias / stream counters / epochs / claimed mass validated BEFORE any conversion
            if zb: fail('zero proof record malformed: %s' % zb); return fails, info
            if [_F(b) for b in (cert.get('bias') or [])] != C.bias: fail('zero proof: recorded bias ledger differs from the replayed one'); return fails, info
            rs_ = cert.get('ratio_stream')                                   # the producer allocates the ratio record at PAC risk BEFORE any draw: it must hold ZERO draws here, as must every epoch
            if (isinstance(rs_, dict) and int(rs_.get('t') or 0) != 0) or any(int(e_.get('t') or 0) for e_ in (cert.get('epochs') or []) if isinstance(e_, dict)): fail('zero proof certificate carries stream draws (a closed zero frontier has none)'); return fails, info
            nf0 = len(fails); fr, _st = _replay_frontier(task, C, cert, delta, work, deadline, fail)
            if fr is None or len(fails) > nf0: return fails, info
            if fr.open or fr.resolved_mass != 0 or fr.Zhi() != 0: fail('replayed frontier is not a closed zero frontier (open %d, resolved mass %s, Zhi %s)' % (len(fr.open), fr.resolved_mass, fr.Zhi())); return fails, info
            if str(zp.get('resolved_mass')) != '0' or zp.get('open_cells') != 0: fail('zero proof record does not state resolved mass 0 with no open cell'); return fails, info
            # ---- transfer to the ORIGINAL model
            commits = [_opname.get(c_.get('op'), c_.get('op')) for c_ in journal if c_.get('kind') == 'commit']
            exact_ops = all(op_ in ZERO_PRESERVING_EXACT_OPS for op_ in commits) and all(b == 0 for b in C.bias) and all(_scalar_positive(sc_) for sc_ in (C.scalars or []))
            if exact_ops: info['zero_transfer'] = dict(method='exact zero-preserving journal (%s): Z_original = positive scalars x Z_compiled' % ','.join(commits) if commits else 'evidence restriction only: Z_original(evidence) = Z_compiled')
            else:
                zs = zero_slice_witness(task['model'], work, deadline)
                if zs is not None: info['zero_transfer'] = dict(method='original-factor zero slice under the evidence', witness=zs)
                else:
                    tr = OR.eliminate_truth(task['model'], task['queries'][:1], deadline=deadline, max_table=ORACLE_CAP) if task['queries'] else None
                    if tr is None: fail('UNVERIFIABLE: zero-mass transfer to the original model could not be established within the allowance (journal commits %s are not all exact zero-preserving; no zero slice; elimination exceeded the cap)' % commits); return fails, info
                    if tr['Z'] != 0: fail('zero-evidence claim contradicted by the independent elimination oracle (Z = %s)' % tr['Z']); return fails, info
                    info['zero_transfer'] = dict(method='independent bounded elimination (Z = 0)')
            info['zero_proof'] = dict(kind='frontier_closed_zero_mass', journal_commits=commits, splits=fr.splits, closures=fr.closures, work=work.snapshot())
        elif zp.get('kind') == 'reference_enumeration':
            tr = OR.enumerate_truth(task['model'], task['queries'], deadline=deadline, max_assignments=ORACLE_CAP)
            if tr is None:
                zs = zero_slice_witness(task['model'], work, deadline)             # the same independent short routes before declaring the claim unverifiable
                if zs is not None: info['zero_transfer'] = dict(method='original-factor zero slice under the evidence', witness=zs)
                else:
                    tr = OR.eliminate_truth(task['model'], task['queries'][:1], deadline=deadline, max_table=ORACLE_CAP) if task['queries'] else None
                    if tr is None: fail('UNVERIFIABLE: zero proof by enumeration exceeds the checker cap / allowance (no zero slice; elimination exceeded the cap)')
                    elif tr['Z'] != 0: fail('zero-evidence claim contradicted by the independent elimination oracle (Z = %s)' % tr['Z'])
                    else: info['zero_transfer'] = dict(method='independent bounded elimination (Z = 0)')
            elif tr['Z'] != 0: fail('zero-evidence claim contradicted by the independent enumerator (Z = %s)' % tr['Z'])
            else: info['zero_transfer'] = dict(method='independent enumeration (Z = 0)')
        else: fail('unknown zero proof kind %s' % zp.get('kind'))
        if w.get('answers') is not None or w.get('intervals') is not None: fail('zero-evidence output carries published answers')
        if not fails and late(): fail('UNVERIFIABLE: the zero proof verification finished after the allowance (a late verification is never an acceptance)')
        return fails, info
    if w.get('outcome') != 'PUBLISHED': return fails, info
    pub = cert.get('publication') or {}; route = pub.get('route'); K = len(task['queries'])
    # ---------------- guarantee class is DERIVED from the route and bound to every label (review CQR-04)
    cls, exact_route = guarantee_class_of_route(route)
    if cls is None: fail('unknown publication route %s' % route); return fails, info
    if not mode_permits(mode, route): fail('route %s is not permitted by the task mode %s (EXACT_RATIONAL needs an exact route; DETERMINISTIC_EPS may not consume a statistical proof)' % (route, mode))
    if cls == 'PAC' and delta == 0: fail('statistical route %s claimed at zero risk (delta = 0 defines no boundary)' % route); return fails, info
    if delta == 0 and cert.get('ratio_stream') is not None: fail('a ratio stream was recorded at zero risk')
    if pub.get('guarantee') != cls: fail('publication guarantee %s differs from the class %s of route %s' % (pub.get('guarantee'), cls, route))
    if w.get('guarantee_type') != cls: fail('worker guarantee_type %s differs from the class %s established by route %s' % (w.get('guarantee_type'), cls, route))
    if bool(pub.get('exact')) != exact_route: fail('exact flag %s disagrees with route %s' % (pub.get('exact'), route))
    # ---------------- 2. compiler JOURNAL replay (second review R1): EXACTLY the recorded commits are verified on their pre-commit model and applied; no operator is re-run,
    # no prefix is guessed; the replayed final model must hash to the recorded final_sha256; every commit's operator must be in the task-effective policy
    comp = cert.get('compile'); C = None
    if comp is not None:
        journal = comp.get('certificates') or []
        C, jf, derived = CP.replay_journal(task, journal, work, deadline=deadline)
        for m_ in jf: fail('journal replay: ' + m_)
        if C is None or jf: return fails, info
        _opname = {'support': 'support_fixpoint'}
        bad_ops = sorted({c.get('op') for c in journal if c.get('kind') == 'commit' and _opname.get(c.get('op'), c.get('op')) not in enabled_eff and c.get('op') != 'evidence'})
        if bad_ops: fail('journal commits by operators outside the task-effective policy: %s' % bad_ops)
        lg = comp.get('log') or {}
        if lg.get('commits') is not None and lg.get('commits') != sum(1 for c in journal if c.get('kind') == 'commit'): fail('log commit count differs from the journal')
        snap = C.snapshot_json(); sha_ = hashlib.sha256(json.dumps(snap, sort_keys=True, default=str).encode()).hexdigest()
        if comp.get('final') is not None and hashlib.sha256(json.dumps(comp.get('final'), sort_keys=True, default=str).encode()).hexdigest() != comp.get('final_sha256'): fail('the recorded final snapshot does not hash to final_sha256 (altered certificate)')
        if sha_ != comp.get('final_sha256'): fail('compiled model does not replay from the journal (final_sha256 %s vs %s)' % (sha_[:12], str(comp.get('final_sha256'))[:12])); return fails, info
        rec_certs = journal
        bias = [_F(b) for b in (cert.get('bias') or [])]
        if bias != C.bias: fail('recorded bias ledger differs from the replayed one')
        if mode == 'EXACT_RATIONAL' and any(b != 0 for b in bias): fail('EXACT_RATIONAL publication with nonzero compiler bias')
        if any(b < 0 for b in bias): fail('negative compiler bias ledger (a bias is an error bound, never negative)')
        if any(b > eps / 4 for b in bias): fail('compiler bias exceeds the reserve eps/4')
        info['commits'] = [c.get('op') for c in journal if c.get('kind') == 'commit']; info['declines'] = [c.get('op') for c in journal if c.get('kind') == 'decline']
        info['bias'] = [str(b) for b in C.bias]; info['compile_outcome'] = dict(interrupted=lg.get('interrupted'), failed=lg.get('failed'))
    else:
        derived = {}; rec_certs = []
        if route not in ('exact_reference', 'normalizer_exact_reference', 'structural_original', 'structural_reduced'): fail('publication without a compile record on a non-reference route'); return fails, info
        # honest absence: the protected reference finished before ANY optional work was spent (no compile transaction opened), or optional work was cancelled
        wo_tot = ((cert.get('work') or {}).get('optional') or {}).get('total')
        if route in ('structural_original', 'structural_reduced'):
            # the structural routes on the original / reduced model publish BEFORE any compile transaction: no optional Work may have been charged (structural executions charge their own counters)
            if wo_tot != 0: fail('%s publication with %s optional Work units charged (the route runs before the compile; a compile record would be required)' % (route, wo_tot))
        elif not cert.get('optional_cancelled') and not (wo_tot == 0 and ((cert.get('reference') or {}).get('done') is True)): fail('compile record absent without a recorded optional cancellation or a reference-first completion with zero optional work')
    if fails: return fails, info
    if late(): fail('UNVERIFIABLE: allowance expired after the compiler replay'); return fails, info
    # ---------------- 3. the PROVEN enclosure of the ORIGINAL answers, per route (compiled units widened by the proved bias)
    if normalizer:
        proven, info_n = _normalizer_enclosure(task, C, cert, pub, route, eps, delta, deadline, work, fail)
        if fails: return fails, info
        _validate_publication(task, w, pub, route, cls, exact_route, proven, mode, eps, fail, normalizer=True)
        info.update(route=route, work=work.snapshot(), exact=exact_route, guarantee=cls, mode=mode); info['attribution'] = _attribution(route, cls, exact_route, C, cert, info); return fails, info
    cq = C.queries if C is not None else None
    proven = None
    def _structural_rows(model, representation):
        """the structural publication record is validated (shape / representation / route consistency / version) and RE-EXECUTED on the bound model under the checker deadline; the rows must
        reproduce exactly (bounded re-execution, as the frozen pac gate verifies R0's structural routes; the kernels' enclosures are TRUSTED at this boundary). Mutations of the route id,
        the representation, the executed route kind, any row, or the model binding are refused here; mutated bounds / points / bias fail the common validator below."""
        rec = pub.get('structural')
        if not isinstance(rec, dict): fail('structural route without its execution record'); return None
        if pub.get('representation') != representation: fail('structural route %s with representation %s' % (route, pub.get('representation'))); return None
        if rec.get('which') != pub.get('which') or rec.get('which') not in ('forest', 'whole_dag', 'components'): fail('structural record route kind %s disagrees with the publication (%s)' % (rec.get('which'), pub.get('which'))); return None
        if not isinstance(rec.get('rows'), list) or not isinstance(rec.get('components'), list): fail('malformed structural record'); return None
        try:
            if F(str(rec.get('epsilon'))) != eps: fail('structural record epsilon %s differs from the task epsilon' % rec.get('epsilon')); return None
        except (ValueError, ZeroDivisionError, TypeError): fail('structural record epsilon is not a rational'); return None
        rows, facts, msg = ST.verify(model, rec, deadline)
        if msg: fail('structural re-execution: ' + msg); return None
        # the AUTHORITATIVE attribution is built from the FACTS of the re-execution (route kind, partition, kinds, native kernels and their verified digests); the producer's timing is labelled an observation
        info['structural'] = dict(route=route, which=facts['which'], components=[dict(kind=c['kind'], variables=len(c['variables'])) for c in facts['components']][:64], native_calls=facts['native_calls'], native_kinds=facts['native_kinds'],
                                  kernel_digests_verified={k: (rec.get('kernel_provenance') or {}).get({'support': 'newarm_cex', 'stream': 'newarm_stream'}[k], {}).get('binary_sha256') for k in facts['native_kinds']},
                                  producer_observed_wall_s=facts['producer_observed_wall_s'], verified_by='bounded re-execution on the bound model (same executors; kernel enclosures TRUSTED at this boundary); rows reproduced exactly; partition / kinds / native use derived from the re-execution; recorded digests equal the verifier\'s loaded kernels')
        return rows
    if route == 'exact_reference':
        tr = OR.enumerate_truth(task['model'], task['queries'], deadline=deadline, max_assignments=ORACLE_CAP)
        if tr is None: fail('UNVERIFIABLE_REFERENCE_SIZE: the exact reference publication exceeds the checker cap / allowance (not shown wrong)'); return fails, info
        proven = [('UNDEFINED' if a == 'UNDEFINED' else (a, a)) for a in tr['answers']]
    elif route in ('structural_original', 'structural_reduced'):
        if C is not None: fail('%s route with a compile record (the route runs before the compile)' % route); return fails, info
        # the singleton correspondence is derived INDEPENDENTLY from each query's TABLE (CQR-S1-01): a query that is not exactly a singleton indicator is not answerable by this route
        targets = ST.singleton_targets(task)
        if any(t is None for t in targets): fail('%s route on a task with a query that is not a singleton indicator (query %d: %s)' % (route, targets.index(None), task['queries'][targets.index(None)].name)); return fails, info
        # presentation labels were validated by their DENOTATION in section 1 (CQR-S2-01); the structural correspondence is `targets`, derived from the tables alone
        m0, why0 = ST.model_from_task(task)
        if m0 is None: fail('%s route on a task outside the adapter domain: %s' % (route, why0)); return fails, info
        if route == 'structural_reduced':
            # RE-DERIVE the reduction on the bound model; the recorded decoder and reduced model must be the re-derived ones; then verify on the reduced model and LIFT
            m1, red1, why1 = ST.model_from_reduced(task, deadline)
            if m1 is None: fail('structural_reduced route but the re-derived reduction declines: %s' % why1); return fails, info
            rr = (pub.get('structural') or {}).get('reduction')
            if not isinstance(rr, dict): fail('structural_reduced publication without its reduction record'); return fails, info
            mine = ST.reduction_record(red1, m1)
            if json.loads(json.dumps(rr.get('decoder'), default=str)) != mine['decoder']: fail('recorded reduction decoder differs from the re-derived one'); return fails, info
            if rr.get('reduced_model_sha256') != mine['reduced_model_sha256']: fail('recorded reduced model differs from the re-derived reduction'); return fails, info
            rows_r = _structural_rows(m1, 'reduced')
            if fails: return fails, info
            rows, _ = ST.lift_rows(red1, rows_r, [[(a + b) / 2 for a, b in row] for row in rows_r]); info['structural']['reduction'] = dict(reduced_variables=len(m1['cards']), original_variables=len(m0['cards']), stats=rr.get('stats'), verified_by='reduction re-derived on the bound model (decoder and reduced model equal); lift re-applied')
        else:
            rows = _structural_rows(m0, 'original')
            if fails: return fails, info
        try: proven = ST.answers_original(task, rows)
        except ValueError as ex: fail('structural answers: %s' % str(ex)[:120]); return fails, info
        RES = TK.output_reservation(task); tau0 = eps - RES
        if [str(x) for x in (pub.get('tau') or [])] != [str(tau0)] * K: fail('%s tau differs from eps - reservation' % route)
    else:
        bias = C.bias
        def widen(x, j):
            if bias[j] < 0: fail('negative bias %s on query %d cannot widen an enclosure' % (bias[j], j)); return (F(1), F(0))       # a reversed interval: refused by the validator as a failed proof
            return (max(F(0), x[0] - bias[j]), min(F(1), x[1] + bias[j]))
        if route == 'structural_compiled':
            if not C.cards: fail('structural_compiled route on a zero-dimensional compiled model'); return fails, info
            m1, why1 = ST.model_from_compiled(C)
            if m1 is None: fail('structural_compiled route on a compiled model outside the adapter domain: %s' % why1); return fails, info
            rows = _structural_rows(m1, 'compiled')
            if fails: return fails, info
            ans = ST.answers_compiled(C, rows); proven = [widen(a, j) for j, a in enumerate(ans)]
            RES = TK.output_reservation(task); tau_c = [eps - bias[j] - RES for j in range(len(cq))]
            if [str(x) for x in (pub.get('tau') or [])] != [str(t) for t in tau_c]: fail('structural_compiled tau differs from eps - bias - reservation')
            cb = pub.get('compiled_bounds')
            if not (isinstance(cb, list) and len(cb) == len(ans) and all(_F(x[0]) == a[0] and _F(x[1]) == a[1] for x, a in zip(cb, ans))): fail('recorded compiled bounds differ from the re-derived structural composition')
        elif not C.cards:
            # zero-dimensional compiled model: every compiled query view has empty scope
            if route not in ('exact_zero_dimensional', 'deterministic_zero_dimensional', 'deterministic_concentration'): fail('route %s on a zero-dimensional compiled model' % route); return fails, info
            if route == 'exact_zero_dimensional' and any(b != 0 for b in bias): fail('exact zero-dimensional route with nonzero bias'); return fails, info
            proven = []
            for j, q in enumerate(cq):
                if q['kind'] == 'expectation': v = q['f'].values[0]; proven.append(widen((v, v), j))
                else: g = q['g'].values[0]; proven.append('UNDEFINED' if g == 0 else widen((q['h'].values[0] / g,) * 2, j))
        else:
            fr, state = _replay_frontier(task, C, cert, delta, work, deadline, fail)
            if fails: return fails, info
            if fr is None: fail('frontier replay unavailable'); return fails, info
            K_ = len(cq); det = fr.deterministic_bounds()
            for j in range(K_):
                if j in C.constant_queries: det[j] = (C.constant_queries[j], C.constant_queries[j])
            positive = fr.resolved_mass > 0 or any(c.L > 0 for c in fr.open.values()) or (C.witness is not None and _witness_weight(C) > 0)       # the replayed witness is RE-EVALUATED on the replayed model
            if not positive: fail('publication without a proved positive mass')
            Lj = [(fr.Zlo() if q['kind'] == 'expectation' else fr.resolved_den[j] + sum(c.L * c.qlo[j][1] for c in fr.open.values())) for j, q in enumerate(cq)]
            undefined = [q['kind'] == 'ratio' and fr.resolved_den[j] == 0 and all(c.B * c.qhi[j][1] == 0 for c in fr.open.values()) for j, q in enumerate(cq)]
            RES = TK.output_reservation(task); tau = [eps - bias[j] - RES for j in range(K_)]
            closed = not fr.open
            if route in ('exact_frontier_closure', 'deterministic_frontier_closure'):
                if not closed: fail('closure route with open cells'); return fails, info
                if route == 'exact_frontier_closure' and any(b != 0 for b in bias): fail('exact closure claimed with nonzero compiler bias (a surrogate is not the original task)'); return fails, info
                proven = []
                for j, q in enumerate(cq):
                    if undefined[j]: proven.append('UNDEFINED'); continue
                    if q['kind'] == 'expectation': v = fr.resolved_num[j] / fr.resolved_mass
                    else: v = fr.resolved_num[j] / fr.resolved_den[j]
                    proven.append(widen((v, v), j))
            elif route in ('deterministic_frontier', 'deterministic_zero_dimensional'):
                proven = [('UNDEFINED' if undefined[j] else widen(det[j], j)) for j in range(K_)]
                for j, q in enumerate(cq):
                    if q['kind'] == 'ratio' and not undefined[j] and Lj[j] <= 0: fail('ratio query %d published without a positive denominator bound' % j)
            elif route == 'deterministic_concentration':
                ca = derived.get('concentration_answers')
                if ca is None: fail('concentration route without an independently re-derived concentration certificate'); return fails, info
                proven = [widen((ca[j], ca[j]), j) for j in range(K_)]
            elif route == 'deterministic_signed_residual_E_zero':
                e = pub.get('epoch'); st = state['epochs'].get(e)
                if st is None: fail('E=0 route without its epoch'); return fails, info
                cells, E = fr.signed_law(st['cand'])
                if E != 0: fail('E = 0 claimed but the replayed envelope is %s' % E)
                proven = []
                for j in range(K_):
                    d = fr.resolved_num[j] - st['cand'][j] * (fr.resolved_mass if cq[j]['kind'] == 'expectation' else fr.resolved_den[j])
                    if Lj[j] <= 0 or abs(d) > tau[j] * Lj[j]: fail('E = 0 residual of query %d does not certify' % j)
                    proven.append(widen((st['cand'][j] - tau[j], st['cand'][j] + tau[j]), j))
                    if _F(pub['point'][j]) != st['cand'][j]: fail('published point differs from the epoch candidate')
            elif route == 'pac_ratio_intersected_with_deterministic':
                rs = state['ratio']
                if rs is None or rs['H'] <= 0: fail('PAC ratio publication without observations'); return fails, info
                B = NM.boundary_upper(rs['U_star'] * rs['U_star'] / 4, rs['V'], delta / 2 / K_); proven = []
                for j in range(K_):
                    if undefined[j]: proven.append('UNDEFINED'); continue
                    if rs['Hj'][j] <= 0: fail('query %d has no denominator statistic' % j); proven.append((F(0), F(1))); continue
                    c = rs['G'][j] / rs['Hj'][j]; r = B / rs['Hj'][j]; lo = max(det[j][0], max(F(0), c - r)); hi = min(det[j][1], min(F(1), c + r))
                    if lo > hi: fail('empty intersection for query %d' % j); proven.append((F(0), F(1))); continue
                    if cq[j]['kind'] == 'ratio' and Lj[j] <= 0: fail('ratio query %d published without a positive denominator bound' % j)
                    proven.append(widen((lo, hi), j))
            elif route == 'pac_signed_residual_validation':
                e = pub.get('epoch'); st = state['epochs'].get(e)
                if st is None or st['H'] <= 0: fail('signed validation without observations'); return fails, info
                B = NM.boundary_upper(st['E_star'] ** 2, st['V'], st['alpha']); proven = []
                for j in range(K_):
                    lo = (st['G'][j] - B) / st['H']; hi = (st['G'][j] + B) / st['H']
                    if Lj[j] <= 0 or lo < -tau[j] * Lj[j] or hi > tau[j] * Lj[j]: fail('signed validation interval of query %d does not fit [-tau L, tau L]' % j)
                    if _F(pub['point'][j]) != st['cand'][j]: fail('published point differs from the validated candidate')
                    proven.append(widen((st['cand'][j] - tau[j], st['cand'][j] + tau[j]), j))
            else: fail('route %s is not valid for a frontier publication' % route); return fails, info
    if fails: return fails, info
    # ---------------- 4. ONE final validator for every route and every emitted representation (review CQR-01 / 03 / 05)
    _validate_publication(task, w, pub, route, cls, exact_route, proven, mode, eps, fail)
    info.update(route=route, work=work.snapshot(), exact=exact_route, guarantee=cls, mode=mode)
    info['attribution'] = _attribution(route, cls, exact_route, C, cert, info)
    return fails, info


def _witness_weight(C):
    w = F(1)
    for v in C.views: w *= v.at(C.cards, C.witness)
    return w


def _validate_publication(task, w, pub, route, cls, exact_route, proven, mode, eps, fail, normalizer=False):
    """the common contract (review item 1): shape / query identity; typed definedness per coordinate; the independently PROVEN enclosure of the original answer lies INSIDE
    the published bounds; the point lies inside the published bounds and within eps - margin of both ends (so every value in the published bounds is within eps of the point);
    exact routes publish zero-width bounds equal to the proven value; EXACT_RATIONAL mode admits only exact coordinates; singleton families sum to one; `answers` agrees
    with the certificate coordinate by coordinate; the legacy rows (when the task is the all-singleton contract) contain the exact bounds and their points agree within
    the rounding margin and form simplex rows; an unexpected legacy representation is refused."""
    K = 1 if normalizer else len(task['queries']); bounds = pub.get('bounds') or []; point = pub.get('point') or []
    if len(bounds) != K or len(point) != K: fail('publication shape differs from the task (%d bounds / %d points for %d queries)' % (len(bounds), len(point), K)); return
    RES = TK.output_reservation(task); tau_pub = eps - RES          # 0 reservation for rational answers: exact equality passes at every supported tolerance (CQR-R3-02)
    for j in range(K):
        pr = proven[j]; b = bounds[j]; pt = point[j]
        if pr == 'UNDEFINED':
            if not (isinstance(b, (list, tuple)) and b[0] == 'UNDEFINED' and b[1] == 'UNDEFINED' and pt == 'UNDEFINED'): fail('query %d is PROVED undefined but a value was published' % j)
            continue
        if b[0] == 'UNDEFINED' or pt == 'UNDEFINED': fail('query %d is defined but published as UNDEFINED' % j); continue
        if not (isinstance(pr, (list, tuple)) and len(pr) == 2 and pr[0] <= pr[1]): fail('query %d: the DERIVED enclosure %s is not an ordered interval (a reversed derivation is a failed proof)' % (j, pr)); continue
        lo, hi = _F(b[0]), _F(b[1]); p = _F(pt)
        if lo > hi: fail('query %d: inverted published bounds' % j); continue
        if normalizer:
            if pr[0] <= 0 or pr[1] < pr[0]: fail('derived Z enclosure [%s, %s] is not a positive ordered interval' % (pr[0], pr[1]))
            if not (lo <= pr[0] and pr[1] <= hi): fail('published Z bounds do not contain the re-derived enclosure [%s, %s]' % (pr[0], pr[1]))
            if lo <= 0: fail('Z lower bound not positive')
            if not ((1 - eps) * hi <= p <= (1 + eps) * lo): fail('Z point outside [(1-eps) U, (1+eps) L] of the PUBLISHED bounds (relative error not certified)')
            if exact_route and not (lo == hi == p == pr[0] == pr[1]): fail('exact normalizer route with a non-exact publication')
            continue
        if not (lo <= pr[0] and pr[1] <= hi): fail('published bounds of query %d do not contain the re-derived enclosure [%s, %s]' % (j, pr[0], pr[1]))
        if not (lo <= p <= hi): fail('point of query %d outside its published bounds' % j)
        if not (hi - tau_pub <= p <= lo + tau_pub): fail('point of query %d is not within eps of every value in its published bounds' % j)
        if exact_route or mode == 'EXACT_RATIONAL':
            if not (lo == hi == p == pr[0] == pr[1]): fail('exact publication of query %d is not the zero-width proven value' % j)
    if normalizer:
        ans = w.get('answers')
        if not (isinstance(ans, list) and len(ans) == 1 and ans[0].get('lo') == str(bounds[0][0]) and ans[0].get('hi') == str(bounds[0][1]) and ans[0].get('point') == str(point[0])): fail('normalizer answer does not agree with the certificate publication')
        if w.get('intervals') is not None or w.get('points') is not None: fail('legacy rows emitted for a normalizer task')
        return
    # simplex rows of singleton families
    for g in SV._singleton_groups(task):
        if any(proven[j] == 'UNDEFINED' for j in g): fail('singleton family contains an undefined coordinate'); continue
        if sum(_F(point[j]) for j in g) != 1: fail('singleton family does not sum to one')
    # answers <-> certificate
    ans = w.get('answers')
    if not isinstance(ans, list) or len(ans) != K: fail('answers shape differs from the task'); return
    for j, a in enumerate(ans):
        if a.get('query') != task['queries'][j].name: fail('answer %d names query %s, not %s' % (j, a.get('query'), task['queries'][j].name))
        if proven[j] == 'UNDEFINED':
            if a.get('status') != 'UNDEFINED': fail('answer %d status %s for a proved-undefined coordinate' % (j, a.get('status')))
        elif a.get('status') != 'OK' or a.get('lo') != str(bounds[j][0]) or a.get('hi') != str(bounds[j][1]) or a.get('point') != str(point[j]): fail('answer %d does not agree with the certificate publication' % j)
    # legacy rows
    iv = w.get('intervals'); pts = w.get('points'); cards = task['model']['cards']
    if task.get('all_singletons') and all(pr != 'UNDEFINED' for pr in proven):
        if iv is None or pts is None: fail('all-singleton task without legacy rows'); return
        if len(iv) != len(cards) or len(pts) != len(cards) or any(len(row) != k or len(pr) != k for row, pr, k in zip(iv, pts, cards)): fail('legacy rows shape differs from the original model'); return
        try:
            IV = [[(F(a), F(b)) for a, b in row] for row in iv]; PT = [[F(x) for x in row] for row in pts]
            from pgm.algorithms.structural import core; core.verify_output(IV, PT, eps)
        except Exception as ex: fail('legacy rows violate the publication contract: %s' % str(ex)[:60]); return
        for j, q in enumerate(task['queries']):
            v_, s_ = TK.singleton_indicator_of(q, cards); lo, hi = IV[v_][s_]; p = PT[v_][s_]            # placement derived from the TABLE (CQR-S1-01), as the worker's legacy_rows does
            if not (lo <= _F(bounds[j][0]) and _F(bounds[j][1]) <= hi): fail('legacy row of query %d does not contain the certified bounds' % j)
            if not (lo <= proven[j][0] and proven[j][1] <= hi): fail('legacy row of query %d does not contain the re-derived enclosure' % j)
            if abs(p - _F(point[j])) > RES: fail('legacy point of query %d differs from the certified point beyond the rounding reservation %s' % (j, RES))
            if not (lo <= p <= hi): fail('legacy point of query %d outside its legacy row' % j)
    elif iv is not None or pts is not None: fail('legacy rows emitted for a task that is not the all-singleton contract (or has undefined coordinates)')




def _replay_frontier(task, C, cert, delta, work, deadline, fail):
    """replay every recorded frontier / stream event on the replayed compiled model; returns (frontier, state) with the recomputed stream statistics; fails on any divergence"""
    cq = C.queries; K = len(cq); fr_rec = cert.get('frontier'); events = cert.get('events') or []; n = len(C.cards)
    # THE PARTITION PREMISE (eighth review, CQR-R7-01): the split order is validated at the data boundary -- a permutation of the compiled variables -- and BOUND to the
    # registered producer policy (canonical) BEFORE any cell is constructed, bound derived or draw replayed: a certificate does not choose the execution structure
    if not isinstance(fr_rec, dict): fail('frontier-based route without a frontier record'); return None, None          # every frontier route of the producer records fr.record()
    if 'order' not in fr_rec: fail('frontier record without a split order'); return None, None
    pb = FR.order_problem(fr_rec['order'], n)
    if pb: fail('frontier order refused: %s' % pb); return None, None
    if list(fr_rec['order']) != FR.canonical_order(n): fail('frontier order %s differs from the registered producer policy (%s): a certificate does not choose the split structure' % (str(list(fr_rec['order']))[:48], FR.FRONTIER_ORDER_POLICY)); return None, None
    try: fr = FR.Frontier(C.cards, C.views, cq, work, order=FR.canonical_order(n))
    except FR.FrontierStructureError as fx: fail('frontier construction refused: %s' % str(fx)[:100]); return None, None
    if deadline is not None:
        def _svc(op):                                                      # the producer's controller hook, here a pure deadline observer (repair-2 review Z-O2): a long closure / bound scan inside ONE replayed event stops at the allowance
            if time.monotonic() >= deadline: raise _ReplayDeadline(op)
        fr.service = _svc
    ratio_rec = cert.get('ratio_stream'); epochs = cert.get('epochs') or []
    H = F(0); Hj = [F(0)] * K; G = [F(0)] * K; V = F(0); t_r = 0
    # the ratio prior U_star is the producer's REGISTERED pre-sampling choice: the initial compiled frontier's positive U (fallback 1 when U = 0), fixed BEFORE any recorded event or
    # draw. It is derived here from the independently constructed root frontier and the record must match it (seventh review, CQR-R6-01); rho = U_star^2 / 4 follows from it
    U0 = fr.U(); U_star = U0 if U0 > 0 else F(1)
    if ratio_rec is not None:
        if not isinstance(ratio_rec, dict) or any(k not in ratio_rec for k in ('U_star', 'rho', 'H', 'G', 'V', 't', 'alpha')): fail('ratio stream record malformed'); return None, None
        try: _F(ratio_rec['U_star']); _F(ratio_rec['rho']); _F(ratio_rec['alpha']); _F(ratio_rec['H']); _F(ratio_rec['V']); [_F(v) for v in ratio_rec['G']]
        except (ValueError, ZeroDivisionError, TypeError): fail('ratio stream record holds a non-rational operand'); return None, None
    if not isinstance(epochs, list) or any(not isinstance(e, dict) or any(k not in e for k in ('epoch', 't', 'H', 'G', 'V')) for e in epochs): fail('epoch records malformed'); return None, None
    if ratio_rec is not None and _F(ratio_rec['U_star']) != U_star: fail('ratio prior U_star %s differs from the registered pre-sampling choice %s (the initial frontier envelope; a prior chosen after the draws is not budgeted)' % (ratio_rec['U_star'], U_star)); return None, None
    ep_state = {}; ep_order = []
    if not isinstance(events, list): fail('certificate events are not a list'); return None, None
    for ev in events:
        if deadline is not None and time.monotonic() >= deadline: fail('UNVERIFIABLE: allowance expired during the frontier replay'); return None, None
        pb = _event_problem(ev)
        if pb: fail('malformed frontier event refused: %s' % pb); return None, None            # the typed boundary of the direct API (ninth review): no field access before validation
        op = ev.get('op')
        try:
          try:
            if op == 'split':
                kids = fr.split(ev['cell'])
                if kids != ev.get('children'): fail('split children differ at cell %s' % ev['cell']); return None, None
            elif op == 'close': fr.close(ev['cell'])
            elif op == 'carve': fr.carve_point(ev['cell'], {int(k): v for k, v in ev['x'].items()})
            elif op == 'ratio_draw':
                cells, U = fr.ratio_law(); c = fr.open.get(ev['cell'])
                if c is None or _F(ev['U']) != U: fail('ratio draw %d: launch law differs (U %s vs %s)' % (t_r + 1, ev['U'], U)); return None, None
                x = {int(k): v for k, v in ev['x'].items()}
                if any(x.get(k) != v for k, v in c.assign.items()) or any(k not in x or not (0 <= x[k] < fr.cards[k]) for k in range(len(fr.cards))): fail('ratio draw point outside its cell'); return None, None
                if _F(ev['A']) != fr.resolved_mass or [_F(v) for v in ev['a']] != fr.resolved_num or [_F(v) for v in ev['d']] != fr.resolved_den: fail('ratio draw %d: pre-trial resolved offsets differ (record-before-resolve violated)' % (t_r + 1)); return None, None
                wgt, fq = fr.weight_and_queries(x); q = c.E / U / c.N; W = wgt / q
                if W > U: fail('importance weight exceeds the cap at draw %d' % (t_r + 1)); return None, None
                b = FR.dyadic_weight((U_star / U) ** 2); t_r += 1; H += b * (fr.resolved_mass + W)
                for j in range(K):
                    fj, gj = fq[j]; G[j] += b * (fr.resolved_num[j] + W * fj); Hj[j] += b * ((fr.resolved_mass + W) if cq[j]['kind'] == 'expectation' else (fr.resolved_den[j] + W * gj))
                V += b * b * U * U / 4
            elif op == 'epoch_start':
                e = ev['epoch']
                # APPEND-ONLY HISTORY (second review R5): epoch ids are the positive integers in order of allocation, each allocated ONCE (its risk delta/(2e(e+1)) is spent once);
                # a new epoch may start only after the previous one is retired (an epoch that still accumulates observations is never restarted or abandoned silently)
                if not isinstance(e, int) or e != len(ep_order) + 1: fail('epoch id %r is not the next allocation (%d)' % (e, len(ep_order) + 1)); return None, None
                if ep_order and ep_state[ep_order[-1]].get('retired') is None: fail('epoch %d started while epoch %d is still open' % (e, ep_order[-1])); return None, None
                de = delta / (2 * e * (e + 1))
                if _F(ev['delta_e']) != de: fail('epoch %d risk differs from delta/(2e(e+1))' % e); return None, None
                cand = [_F(c_) for c_ in ev['candidate']]; cells, E0 = fr.signed_law(cand, key=('epoch', e))
                if _F(ev['E_star']) != (E0 if E0 > 0 else F(1)): fail('epoch %d E_star differs from the launch envelope' % e); return None, None
                ep_state[e] = dict(cand=cand, H=F(0), G=[F(0)] * K, V=F(0), t=0, E_star=_F(ev['E_star']), alpha=de / max(1, K), retired=None); ep_order.append(e)
            elif op in ('epoch_retired', 'epoch_E_zero'):
                st = ep_state.get(ev.get('epoch'))
                if st is None: fail('%s for an epoch that never started' % op); return None, None
                if op == 'epoch_retired' or not ev.get('certified'): st['retired'] = ev.get('reason') or op
            elif op == 'signed_draw':
                st = ep_state.get(ev['epoch'])
                if st is None: fail('signed draw before its epoch start'); return None, None
                if ev['epoch'] != ep_order[-1] or st.get('retired') is not None: fail('signed draw for epoch %s which is not the current open epoch' % ev['epoch']); return None, None
                cells, E = fr.signed_law(st['cand'], key=('epoch', ev['epoch'])); c = fr.open.get(ev['cell'])
                if c is None or _F(ev['E']) != E: fail('signed draw: launch envelope differs (E %s vs %s)' % (ev['E'], E)); return None, None
                a_c = next((a for cc, a in cells if cc.id == c.id), None)
                if a_c is None or _F(ev['p']) != a_c / E: fail('signed draw: cell probability differs'); return None, None
                rn = fr.resolved_num; rd_ = fr.resolved_den; rm = fr.resolved_mass; d = [rn[j] - st['cand'][j] * (rm if cq[j]['kind'] == 'expectation' else rd_[j]) for j in range(K)]
                if [_F(v) for v in ev['d']] != d: fail('signed draw: pre-trial offsets differ'); return None, None
                x = {int(k): v for k, v in ev['x'].items()}
                if any(x.get(k) != v for k, v in c.assign.items()) or any(k not in x or not (0 <= x[k] < fr.cards[k]) for k in range(len(fr.cards))): fail('signed draw point outside its cell'); return None, None
                wgt, fq = fr.weight_and_queries(x); b = FR.dyadic_weight((st['E_star'] / E) ** 2); st['t'] += 1; st['H'] += b
                for j in range(K):
                    fj, gj = fq[j]; R = wgt * (fj - st['cand'][j] * gj) / (a_c / E / c.N)
                    if abs(R) > E: fail('signed contribution exceeds E'); return None, None
                    st['G'][j] += b * (d[j] + R)
                st['V'] += b * b * E * E
            elif op in ('ratio_stream_stopped', 'prune_zero', 'optional_cancelled', 'optional_operator_failed'): pass      # informational: the compile replay / rollback is verified separately
            else: fail('unknown event %s' % op); return None, None
          except _ReplayDeadline as dx: fail('UNVERIFIABLE: allowance expired inside the replay of event %s (%s)' % (op, dx)); return None, None
        except FR.FrontierStructureError as fx: fail('frontier structure violated during the replay: %s' % str(fx)[:100]); return None, None
        except AssertionError as ax: fail('frontier replay assertion: %s' % str(ax)[:80]); return None, None
        except (KeyError, TypeError, ValueError, IndexError) as ex: fail('frontier event %s is malformed or refers to a cell that is not open (%s)' % (op, type(ex).__name__)); return None, None
    if fr.resolved_mass != _F(fr_rec['resolved_mass']) or [str(x) for x in fr.resolved_num] != fr_rec['resolved_num'] or len(fr.open) != fr_rec['open_cells']: fail('replayed frontier totals differ from the recorded frontier')
    ratio = None
    if ratio_rec is not None:
        if t_r != ratio_rec['t'] or str(H) != ratio_rec['H'] or [str(x) for x in G] != ratio_rec['G'] or str(V) != ratio_rec['V']: fail('ratio stream statistics do not replay')
        if _F(ratio_rec['alpha']) != delta / 2 / max(1, K) or _F(ratio_rec['rho']) != U_star * U_star / 4: fail('ratio stream risk / rho differ from the policy (rho must be the bound prior squared over four)')
        ratio = dict(H=H, Hj=Hj, G=G, V=V, t=t_r, U_star=U_star, Hb=None)
    # every start reconciles with exactly one epoch record and vice versa; every completed draw was counted in exactly one epoch (t sums); the records carry the replayed statistics
    if [e.get('epoch') for e in epochs] != ep_order: fail('epoch records %s do not match the started epochs %s' % ([e.get('epoch') for e in epochs], ep_order))
    n_draws = sum(1 for ev in events if ev.get('op') == 'signed_draw')
    if sum(st['t'] for st in ep_state.values()) != n_draws: fail('completed signed draws (%d) are not all accounted in the epochs' % n_draws)
    for e in epochs:
        st = ep_state.get(e['epoch'])
        if st is None: fail('recorded epoch %s has no start event' % e['epoch']); continue
        if st['t'] != e['t'] or str(st['H']) != e['H'] or [str(x) for x in st['G']] != e['G'] or str(st['V']) != e['V']: fail('epoch %s statistics do not replay' % e['epoch'])
        if len(e.get('draws') or []) != e['t']: fail('epoch %s draw records (%d) differ from its count t = %d' % (e['epoch'], len(e.get('draws') or []), e['t']))
    return fr, dict(ratio=ratio, epochs=ep_state)






def _normalizer_enclosure(task, C, cert, pub, route, eps, delta, deadline, work, fail):
    """the PROVEN enclosure [L, U] of Z in ORIGINAL units (scale_den and the KNOWN scalars); the common validator then requires it INSIDE the published bounds (review CQR-02)"""
    if C is None:
        if route != 'normalizer_exact_reference': fail('normalizer publication without a compile record on a non-reference route'); return None, {}
    else:
        if any(d.get('kind') == 'omitted_component_mass' for d in C.scalars): fail('normalizer task with an omitted component (unknown scalar)'); return None, {}
    if route == 'normalizer_exact_reference':
        tr = OR.enumerate_truth(task['model'], task['queries'], deadline=deadline, max_assignments=ORACLE_CAP)
        if tr is None: fail('UNVERIFIABLE_REFERENCE_SIZE: exact Z publication exceeds the checker cap'); return None, {}
        return [(tr['Z'], tr['Z'])], {}
    sc = F(1)
    for d in C.scalars: sc *= F(d['value'])
    for d in C.constant_scalars: sc *= F(d['value'])
    if str(sc) != str(pub.get('scale', str(sc))): fail('known scalar product differs (%s vs %s)' % (sc, pub.get('scale')))
    if not C.cards:
        if route != 'normalizer_exact_zero_dimensional': fail('zero-dimensional normalizer route %s' % route)
        return [(sc, sc)], {}
    fr, state = _replay_frontier(task, C, cert, delta, work, deadline, fail)
    if fr is None: return None, {}
    if any(e.get('op') in ('epoch_start', 'signed_draw') for e in (cert.get('events') or [])): fail('signed stream events in a normalizer run')
    L = fr.Zlo() / fr.scale_den * sc; Uz = fr.Zhi() / fr.scale_den * sc
    if route == 'normalizer_exact_frontier_closure':
        if fr.open: fail('exact closure with open cells'); return None, {}
        z = fr.resolved_mass / fr.scale_den * sc; return [(z, z)], {}
    if route == 'normalizer_deterministic_frontier': return [(L, Uz)], {}
    if route == 'normalizer_pac_ratio_intersected_with_deterministic':
        rs = state['ratio']
        if rs is None or rs['t'] == 0: fail('ratio stream does not replay'); return None, {}
        Hb = sum(FR.dyadic_weight((rs['U_star'] / _F(ev['U'])) ** 2) for ev in (cert.get('events') or []) if ev.get('op') == 'ratio_draw')
        B = NM.boundary_upper(rs['U_star'] * rs['U_star'] / 4, rs['V'], delta / 2 / max(1, len(C.queries)))
        zl = max(F(0), (rs['H'] - B) / Hb) / fr.scale_den * sc; zu = (rs['H'] + B) / Hb / fr.scale_den * sc; l2 = max(L, zl); u2 = min(Uz, zu)
        if l2 > u2: fail('empty Z intersection'); return None, {}
        return [(l2, u2)], {}
    fail('unknown normalizer route %s' % route); return None, {}
