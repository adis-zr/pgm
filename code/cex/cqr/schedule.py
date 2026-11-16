"""Constructed query / evidence schedule of the 96 constructed slots (pure, deterministic, stdlib only).

The resolved design (cex/cqr/resolve_design.py, module docstring and rules.constructed_schedule) declares:

    slot index i over the 96 slots in (family, n, regime, seed_index) order; r = i mod 8; query kind = KINDS[r mod 4];
    evidence regime = EVIDENCE[r div 4]; KINDS = selected_singleton, all_singletons, selected_pair_joint, parity_or_modular_sum;
    EVIDENCE = no_evidence, nontrivial_evidence.

and, for selected variables / states, the public query-transfer hash rule of the same document:

    h(name,k) = int(sha256(SALT|name|k), 16); v1 = free[h1 mod |free|] state h4 mod card; v2 = free[h2 mod |free|] (v2 != v1: smallest
    forward shift t >= 0), state h5 mod card; v3 = free[h3 mod |free|] (not in {v1,v2}: smallest forward shift); parity over {v1,v2,v3}
    with bit h8 mod 2; joint over (v1, v3) with states h6 mod card(v1), h7 mod card(v3). free = variables not in the evidence.

This module materializes that schedule from exactly the rule's inputs (slot_index, cards, salt, name):

    evidence   no_evidence         -> {}
               nontrivial_evidence -> E = max(1, n div 8) variables e_j = pick over h(name, 100+j) (distinct, smallest forward shift),
                                      states h(name, 200+j) mod card(e_j); 'nontrivial' = at least one variable fixed; the query never
                                      touches an evidence variable (free = variables not in E), exactly as in the query-transfer rule.
    query      selected_singleton      -> {'kind':'singleton','variable':v1,'state':s1}
               all_singletons          -> {'kind':'all_singletons'}
               selected_pair_joint     -> {'kind':'joint','assign':{v1: h6 mod card(v1), v3: h7 mod card(v3)}}
               parity_or_modular_sum   -> {'kind':'parity','variables':sorted[v1,v2,v3],'bit':h8 mod 2}   (task.py: parity of the state index for
                                          non-binary variables = bounded modular-sum query)

`cards` is the generated model's cardinality list, which for several families depends on the generator seed and therefore on the held-out seed
root: without cards only (r, query_kind, evidence_regime) and the cards-free combination all_singletons x no_evidence can be materialized.
Nothing here is chosen at run time; `check_schedule` re-derives every cell independently from the same inputs.
"""
import hashlib, json

KINDS = ('selected_singleton', 'all_singletons', 'selected_pair_joint', 'parity_or_modular_sum')
EVIDENCE = ('no_evidence', 'nontrivial_evidence')
EPS, DELTA, MODE = '1/200', '1/1000000', 'PAC_EPS'
SCHEDULE_VERSION = 'cqr-constructed-schedule-v1 (2026-11-16)'
RULE = 'r = slot_index mod 8; query_kind = KINDS[r mod 4]; evidence_regime = EVIDENCE[r div 4]; variables/states by h(name,k) = int(sha256(salt|name|k),16) per the query-transfer rule; evidence = max(1, n div 8) hashed variables (k = 100+j / 200+j)'
DEFERRED = 'DEFERRED_UNTIL_HELDOUT_SEED_ROOT_FIXED'


def h_name(salt, name, k): return int(hashlib.sha256(('%s|%s|%d' % (salt, name, k)).encode()).hexdigest(), 16)


def canonical(spec): return json.dumps(spec, sort_keys=True, separators=(',', ':'))


def qsha(spec): return hashlib.sha256(canonical(spec).encode()).hexdigest()


def slot_kind(slot_index):
    r = int(slot_index) % 8
    return dict(r=r, query_kind=KINDS[r % 4], evidence_regime=EVIDENCE[r // 4])


def _pick(free, base, exclude):
    t = 0
    while free[(base + t) % len(free)] in exclude: t += 1
    return free[(base + t) % len(free)], t


def constructed_schedule(slot_index, cards, salt, name, mode=MODE, epsilon=EPS, delta=DELTA):
    """-> dict(query_spec, evidence, r, query_kind, evidence_regime, selection, status). cards=None: only the slot part (status DEFERRED) unless the
    combination needs no cards (all_singletons x no_evidence), which is materialized in full."""
    sk = slot_kind(slot_index); r, qk, er = sk['r'], sk['query_kind'], sk['evidence_regime']
    out = dict(schedule_version=SCHEDULE_VERSION, rule=RULE, slot_index=int(slot_index), name=name, r=r, query_kind=qk, evidence_regime=er)
    if cards is None:
        if qk == 'all_singletons' and er == 'no_evidence':
            spec = dict(mode=mode, queries=[dict(kind='all_singletons')], epsilon=epsilon, delta=delta)
            out.update(status='RESOLVED', cards_needed=False, evidence={}, query_spec=spec, query_canonical_json=canonical(spec), query_sha256=qsha(spec), selection=dict(note='no variable selection: all_singletons x no_evidence needs no cardinalities'))
            return out
        out.update(status=DEFERRED, cards_needed=True, evidence=None, query_spec=None, query_sha256=None, selection=None,
                   deferred_reason='the selected variables / states / evidence depend on the generated model cardinalities, which depend on the held-out seed root')
        return out
    cards = [int(c) for c in cards]; n = len(cards)
    if n < 4 or any(c < 2 for c in cards): raise ValueError('constructed_schedule: need n >= 4 and every card >= 2 (n=%d)' % n)
    # ---- evidence
    evidence = {}; ev_rec = []
    if er == 'nontrivial_evidence':
        E = max(1, n // 8); allv = list(range(n))
        for j in range(E):
            v, t = _pick(allv, h_name(salt, name, 100 + j) % n, set(evidence)); s = h_name(salt, name, 200 + j) % cards[v]
            evidence[v] = s; ev_rec.append(dict(variable=v, state=s, shift=t))
    free = [v for v in range(n) if v not in evidence]
    if len(free) < 3: raise ValueError('constructed_schedule: fewer than 3 free variables (n=%d, evidence=%d)' % (n, len(evidence)))
    # ---- query (the query-transfer hash rule over the free variables)
    v1, t1 = _pick(free, h_name(salt, name, 1) % len(free), set())
    v2, t2 = _pick(free, h_name(salt, name, 2) % len(free), {v1})
    v3, t3 = _pick(free, h_name(salt, name, 3) % len(free), {v1, v2})
    sel = dict(v1=v1, v2=v2, v3=v3, cards=[cards[v1], cards[v2], cards[v3]], shifts=dict(v1=t1, v2=t2, v3=t3), evidence=ev_rec, n=n, n_free=len(free))
    if qk == 'selected_singleton': q = dict(kind='singleton', variable=v1, state=h_name(salt, name, 4) % cards[v1])
    elif qk == 'all_singletons': q = dict(kind='all_singletons')
    elif qk == 'selected_pair_joint': q = dict(kind='joint', assign={str(v1): h_name(salt, name, 6) % cards[v1], str(v3): h_name(salt, name, 7) % cards[v3]})
    else: q = dict(kind='parity', variables=sorted([v1, v2, v3]), bit=h_name(salt, name, 8) % 2)
    spec = dict(mode=mode, queries=[q], epsilon=epsilon, delta=delta)
    out.update(status='RESOLVED', cards_needed=True, evidence={str(v): s for v, s in sorted(evidence.items())}, query_spec=spec, query_canonical_json=canonical(spec), query_sha256=qsha(spec), selection=sel)
    return out


def check_schedule(cells, salt=None):
    """independently re-derive every constructed cell's schedule from (slot_index, cards, salt, name) and report mismatches.
    A cell is a dict with slot_index, slot_id (or name), optional cards, optional salt (else the `salt` argument), and a `schedule` dict as written by
    constructed_schedule (legacy rows carrying only query_schedule={r, query_kind, evidence_regime} are checked on those three fields).
    -> dict(checked, resolved, deferred, mismatches=[...])"""
    mism = []; checked = resolved = deferred = 0
    for c in cells:
        if c.get('cohort') not in (None, 'constructed') or 'slot_index' not in c: continue
        checked += 1; sched = c.get('schedule') or c.get('query_schedule') or {}; name = c.get('name') or c.get('slot_id'); s = c.get('salt', salt)
        exp = constructed_schedule(c['slot_index'], c.get('cards'), s, name) if (s is not None and name is not None) else dict(slot_kind(c['slot_index']), status=None)
        for k in ('r', 'query_kind', 'evidence_regime'):
            if sched.get(k) != exp[k]: mism.append(dict(slot=name, field=k, cell=sched.get(k), expected=exp[k]))
        if 'query_spec' in sched or 'evidence' in sched or exp.get('status') == 'RESOLVED':
            if exp.get('status') == 'RESOLVED':
                resolved += 1
                for k in ('query_spec', 'evidence', 'query_sha256'):
                    if sched.get(k) != exp.get(k): mism.append(dict(slot=name, field=k, cell=sched.get(k), expected=exp.get(k)))
                if sched.get('status') != 'RESOLVED': mism.append(dict(slot=name, field='status', cell=sched.get('status'), expected='RESOLVED'))
            else:
                deferred += 1
                if sched.get('query_spec') is not None or sched.get('evidence') not in (None, {}) and sched.get('evidence') is not None:
                    mism.append(dict(slot=name, field='materialized_without_cards', cell=sched.get('query_spec'), expected=None))
                if sched.get('status') not in (None, DEFERRED): mism.append(dict(slot=name, field='status', cell=sched.get('status'), expected=DEFERRED))
    return dict(checked=checked, resolved=resolved, deferred=deferred, mismatches=mism, ok=(not mism))


def coverage(slot_indices):
    """every family (8 consecutive slots) receives all 8 (kind x regime) combinations once -> True when the 96-slot enumeration satisfies that"""
    by_fam = {}
    for i in slot_indices: by_fam.setdefault(int(i) // 8, set()).add(int(i) % 8)
    return all(v == set(range(8)) for v in by_fam.values()) and len(by_fam) * 8 == len(set(slot_indices))


if __name__ == '__main__':
    import sys
    print(json.dumps(constructed_schedule(int(sys.argv[1]), [int(x) for x in sys.argv[2].split(',')] if len(sys.argv) > 2 and sys.argv[2] else None, sys.argv[3] if len(sys.argv) > 3 else 'salt', sys.argv[4] if len(sys.argv) > 4 else 'name'), indent=1))
