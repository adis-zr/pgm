"""Weighted CNF (MC 2024 Track 2 format) parsing and exact WCNF -> UAI (MARKOV) conversion.

Standard library only.  Nothing here runs inference on an instance: the only summations are the
brute-force enumerations used by the CONVERSION CERTIFICATE on tiny (n <= 12) problems.

File format actually observed in mc2024-track2-wmc_competition.tar (recorded, not assumed):
    c t wmc
    c file <name>.cnf
    p cnf <n> <m>
    c p weight <lit> <w> 0        # one line per literal, decimal weight strings
    <lit> ... 0                    # clauses, one per line, 0-terminated
The organisers' Track 2 rule is "only weights w_l + w_-l = 1 or none"; "none" appears in the files either as the
unit pair (1, 1) on both literals or as no weight line at all for a variable (both cases are counted separately).
Weights are accepted when they are nonnegative rationals: a decimal literal  [+]digits[.digits][e[+-]digits]
or an explicit fraction  digits/digits .  Anything else (a leading '-', inf, nan, words) refuses the instance
with REFUSED_NEGATIVE_OR_NONRATIONAL_WEIGHT (the instance is kept as a parser-refusal control row).

Conversion (exact, weighted count == UAI partition function Z):
  * CNF variable i (1..n) -> UAI variable i-1, cardinality 2, state 1 = true.
  * literal weights  -> unary factor over i-1 with table [w(-i), w(+i)]  (missing weight -> 1, recorded).
  * clause of effective length k <= 3 -> one factor over its (distinct) variables, value 1 iff satisfied.
  * clause of effective length k >  3 -> k-2 auxiliary variables y_1..y_{k-2} (cardinality 2) through
    deterministic OR gates of arity 3:  y_1 = l_1 v l_2 ;  y_j = y_{j-1} v l_{j+1}  (j = 2..k-2) ;
    final factor 1[y_{k-2} v l_k] of arity 2.  Every gate factor is 1 iff the output equals the OR of its two
    inputs (under the literal signs) and 0 otherwise, so for every assignment of the original variables
    exactly one auxiliary assignment has nonzero product and its product equals the clause indicator.
    Hence Z(UAI) = sum_x prod_i w_i(x_i) prod_C [C satisfied](x) = WMC(CNF) exactly.
  * repeated literals inside a clause are merged; a tautological clause (x and -x) is dropped (always
    satisfied, weight preserving); an empty clause is encoded as a unary all-zero factor (Z = 0).
Table size of the converted model = 2n + sum_C (2^k if k <= 3 else 8(k-2) + 4).
"""
from __future__ import annotations
from ._paths import HERE, ROOT, CODE, CEX, PAC, NEWARM, RUNTIME, PY, runs_root, source_path, subprocess_env
import hashlib, json, lzma, os, re, sys
from fractions import Fraction
from itertools import product

WEIGHT_RE = re.compile(r'^\+?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$')
FRAC_RE = re.compile(r'^\+?\d+/\d+$')
HEADER_RE = re.compile(r'^p\s+cnf\s+(\d+)\s+(\d+)\s*$')
WEIGHT_LINE_RE = re.compile(r'^c\s+p\s+weight\s+(-?\d+)\s+(\S+)\s+0\s*$')
TYPE_LINE_RE = re.compile(r'^c\s+t\s+([A-Za-z]+)\s*$')                 # 'c t wmc' / 'c t mc' / 'c t pmc' / 'c t pwmc' (MC competition header)
SHOW_LINE_RE = re.compile(r'^c\s+p\s+show\b')                        # projection set declaration (projected counting)
PROJECTED_TYPES = ('pmc', 'pwmc')
ACCEPTED_TYPES = ('wmc', 'mc', None)



def classify_weight(s):
    """'rational_nonneg' | 'negative' | 'nonrational'  for a weight token"""
    if WEIGHT_RE.match(s) or FRAC_RE.match(s):
        return 'rational_nonneg'
    t = s[1:] if s.startswith('-') else s
    if WEIGHT_RE.match(t) or FRAC_RE.match(t):
        return 'negative'
    return 'nonrational'


def open_text(path):
    if str(path).endswith('.xz'):
        return lzma.open(path, 'rt', encoding='ascii', errors='strict')
    return open(path, 'r', encoding='ascii', errors='strict')


def scan_wcnf(path, keep_clauses=False, hash_bytes=True):
    """One streaming pass over a (possibly .xz) weighted CNF.

    Returns a dict of metadata (header n/m, clause counts, max clause length, weight statistics, converted
    UAI table size, weight problems) and, when keep_clauses, the clause list (deduplicated literal tuples)
    and the weight dict {lit: weight_string}.  Weight normalisation is checked exactly as rationals using
    integer decimal arithmetic (Decimal with ample precision) and also in float64 (what the organisers'
    "w_l + w_-l = 1" plausibly meant)."""
    from decimal import Decimal, getcontext
    getcontext().prec = 120
    n = m = None; clauses = []; weights = {}; n_clauses = 0; max_len = 0; max_eff_len = 0
    bad = []; weight_lines = 0; dup_weight_lines = 0; tautologies = 0; empty_clauses = 0; dup_literal_clauses = 0
    table_entries = 0; aux_vars = 0; other_comment_lines = 0; header_lines = []; sha = hashlib.sha256(); nbytes = 0
    out_of_range_weight_lits = 0; nonnorm_exact = 0; nonnorm_f64 = 0; nonnorm_examples = []; pending = []
    max_digits = 0
    declared_type = None; type_lines = 0; show_lines = 0; show_examples = []     # 'c t <type>' (wmc / mc / pmc / pwmc) and 'c p show ...' (projected counting; CQR-10)
    with open_text(path) as fh:
        for line in fh:
            if hash_bytes:
                b = line.encode('ascii'); sha.update(b); nbytes += len(b)
            if not line.strip():
                continue
            c0 = line[0]
            if c0 == 'c':
                mw = WEIGHT_LINE_RE.match(line)
                if mw:
                    weight_lines += 1; lit = int(mw.group(1)); w = mw.group(2)
                    if n is not None and not (1 <= abs(lit) <= n):
                        out_of_range_weight_lits += 1
                    if lit in weights:
                        dup_weight_lines += 1
                    weights[lit] = w
                    kind = classify_weight(w)
                    if kind != 'rational_nonneg':
                        bad.append({'lit': lit, 'weight': w, 'kind': kind})
                    max_digits = max(max_digits, sum(ch.isdigit() for ch in w))
                else:
                    mt = TYPE_LINE_RE.match(line); ms = SHOW_LINE_RE.match(line)
                    if mt:
                        type_lines += 1
                        if declared_type is None: declared_type = mt.group(1).lower()
                        elif declared_type != mt.group(1).lower(): declared_type = 'CONFLICTING'
                    elif ms:
                        show_lines += 1
                        if len(show_examples) < 3: show_examples.append(line.rstrip('\n')[:120])
                    other_comment_lines += 1
                    if len(header_lines) < 4:
                        header_lines.append(line.rstrip('\n')[:120])
                continue
            if c0 == 'p':
                mh = HEADER_RE.match(line)
                if not mh:
                    raise ValueError('unrecognised p-line: %r' % line[:80])
                n, m = int(mh.group(1)), int(mh.group(2))
                continue
            for tok in line.split():
                v = int(tok)
                if v != 0:
                    pending.append(v); continue
                raw_len = len(pending); max_len = max(max_len, raw_len)
                eff = tuple(dict.fromkeys(pending))      # merge repeated literals, keep first-seen order
                if len(eff) != raw_len:
                    dup_literal_clauses += 1
                vs = set(abs(l) for l in eff)
                if len(vs) != len(eff):
                    tautologies += 1; n_clauses += 1; pending = []
                    if keep_clauses:
                        clauses.append(None)
                    continue
                k = len(eff); n_clauses += 1
                if k == 0:
                    empty_clauses += 1; table_entries += 2
                elif k <= 3:
                    table_entries += 2 ** k
                else:
                    table_entries += 8 * (k - 2) + 4; aux_vars += k - 2
                max_eff_len = max(max_eff_len, k)
                if keep_clauses:
                    clauses.append(eff)
                pending = []
    if pending:
        raise ValueError('clause not terminated by 0')
    if n is None:
        raise ValueError('no p cnf header')
    both = 0; missing_pos = 0; missing_neg = 0; unit_pairs = 0; neither = 0; other_pairs = 0
    for v in range(1, n + 1):
        wp = weights.get(v); wn = weights.get(-v)
        if wp is not None and wn is not None:
            both += 1
            if classify_weight(wp) == 'rational_nonneg' and classify_weight(wn) == 'rational_nonneg':
                fp = Fraction(_frac_str(wp)); fn_ = Fraction(_frac_str(wn))
                if fp == 1 and fn_ == 1:
                    unit_pairs += 1          # the organisers' "or none": an unweighted variable written as the pair (1, 1)
                    continue
                dp = _to_decimal(wp); dn = _to_decimal(wn)
                if dp is None or dn is None or dp + dn != 1:
                    nonnorm_exact += 1
                    if len(nonnorm_examples) < 3:
                        nonnorm_examples.append([v, wp, wn])
                if float(fp + fn_) != 1.0:
                    nonnorm_f64 += 1; other_pairs += 1
        else:
            missing_pos += wp is None; missing_neg += wn is None
            if wp is None and wn is None:
                neither += 1               # "none" written as no weight line at all (converter uses 1, 1)
    table_entries += 2 * n
    meta = dict(n_vars=n, m_header=m, n_clauses_parsed=n_clauses, header_matches=(m == n_clauses),
                max_clause_length_raw=max_len, max_clause_length_effective=max_eff_len,
                n_weight_lines=weight_lines, duplicate_weight_lines=dup_weight_lines, out_of_range_weight_literals=out_of_range_weight_lits,
                vars_with_both_literal_weights=both, vars_missing_positive_weight=missing_pos, vars_missing_negative_weight=missing_neg,
                both_literal_weights_given_for_all_vars=(both == n), vars_unit_pair_1_1=unit_pairs, vars_no_weight_line_at_all=neither,
                vars_weighted_pairs=both - unit_pairs,
                normalized_exact_rational=(nonnorm_exact == 0 and both == n), vars_not_normalized_exact=nonnorm_exact,
                normalized_float64=(nonnorm_f64 == 0 and both == n), vars_not_normalized_float64=nonnorm_f64,
                normalized_or_unit_exact=(nonnorm_exact == 0 and missing_pos == 0 and missing_neg == 0),
                normalized_or_none_float64=(nonnorm_f64 == 0 and missing_pos == neither and missing_neg == neither),
                vars_weighted_pair_not_normalized_float64=other_pairs,
                nonnormalized_examples=nonnorm_examples, max_weight_significant_digits=max_digits,
                refused_weights=bad[:20], n_refused_weights=len(bad),
                weight_status=('OK' if not bad else 'REFUSED_NEGATIVE_OR_NONRATIONAL_WEIGHT'),
                declared_type=declared_type, type_lines=type_lines, show_lines=show_lines, show_examples=show_examples,
                projected_semantics=(declared_type in PROJECTED_TYPES or show_lines > 0),
                count_semantics_status=('REFUSED_PROJECTED_COUNT_SEMANTICS' if (declared_type in PROJECTED_TYPES or show_lines > 0) else 'OK'),
                tautological_clauses=tautologies, empty_clauses=empty_clauses, clauses_with_repeated_literals=dup_literal_clauses,
                converted_table_entries=table_entries, converted_auxiliary_vars=aux_vars, converted_n_vars=n + aux_vars,
                converted_n_factors=n + n_clauses - tautologies,
                other_comment_lines=other_comment_lines, first_comment_lines=header_lines,
                cnf_bytes=nbytes if hash_bytes else None, cnf_sha256=sha.hexdigest() if hash_bytes else None)
    if keep_clauses:
        return meta, clauses, weights
    return meta


def _frac_str(s):
    return s[1:] if s.startswith('+') else s


def _to_decimal(s):
    from decimal import Decimal, InvalidOperation
    s = _frac_str(s)
    if '/' in s:
        a, b = s.split('/')
        if int(b) == 0:
            return None
        f = Fraction(int(a), int(b))
        # exact only when the denominator is 2^a 5^b; otherwise compare via Fraction instead
        d = Decimal(f.numerator) / Decimal(f.denominator)
        return d if Fraction(d) == f else None
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def lit_true(lit, x):
    """x: dict/list of UAI states for original variables (index lit-1); state 1 = true"""
    v = abs(lit) - 1
    return x[v] == (1 if lit > 0 else 0)


def convert(cnf_path, uai_path, name=None, cap_entries=None):
    """Write <uai_path> (MARKOV), <uai_path>.evid ('0') and <uai_path>.conversion.json.  Returns the sidecar dict.
    Refuses (ValueError) on negative / nonrational weights; raises CapExceeded when the table total would exceed cap."""
    meta, clauses, weights = scan_wcnf(cnf_path, keep_clauses=True)
    if meta['weight_status'] != 'OK':
        raise ValueError('REFUSED_NEGATIVE_OR_NONRATIONAL_WEIGHT: %s' % meta['refused_weights'][:3])
    if meta['count_semantics_status'] != 'OK':
        # CQR-10: projected (weighted) model counting sums over the SHOWN variables only; the ordinary count over all variables differs
        # (the reviewer's control 'c t pmc / c p show 1 0 / p cnf 2 1 / 1 0' has ordinary count 2, projected count 1). The converter emits
        # ordinary WMC factors, so such a file is refused rather than silently treated as WMC.
        raise ValueError('REFUSED_PROJECTED_COUNT_SEMANTICS: declared_type=%s show_lines=%d %s' % (meta['declared_type'], meta['show_lines'], meta['show_examples'][:1]))
    if cap_entries is not None and meta['converted_table_entries'] > cap_entries:
        raise CapExceeded(meta['converted_table_entries'])
    n = meta['n_vars']; next_var = n; factors = []     # factor = (scope tuple, values list of strings)
    missing = []
    for v in range(1, n + 1):
        wn = weights.get(-v); wp = weights.get(v)
        if wn is None:
            missing.append(-v); wn = '1'
        if wp is None:
            missing.append(v); wp = '1'
        factors.append(((v - 1,), [_frac_str(wn), _frac_str(wp)]))
    clause_factor_start = []; clause_aux_start = []; aux_total = 0; dropped_tautologies = []
    for ci, cl in enumerate(clauses):
        clause_factor_start.append(len(factors)); clause_aux_start.append(next_var)
        if cl is None:
            dropped_tautologies.append(ci); continue
        k = len(cl)
        if k == 0:
            factors.append(((0,), ['0', '0'])); continue
        if k <= 3:
            scope = tuple(abs(l) - 1 for l in cl)
            vals = []
            for xs in product((0, 1), repeat=k):
                sat = any((xs[i] == 1) == (cl[i] > 0) for i in range(k))
                vals.append('1' if sat else '0')
            factors.append((scope, vals)); continue
        # chain of OR gates
        y_prev = None
        for j in range(k - 2):
            y = next_var; next_var += 1; aux_total += 1
            if j == 0:
                a_var, a_pos = abs(cl[0]) - 1, cl[0] > 0
            else:
                a_var, a_pos = y_prev, True
            b_var, b_pos = abs(cl[j + 1]) - 1, cl[j + 1] > 0
            vals = []
            for xa, xb, xy in product((0, 1), repeat=3):
                o = ((xa == 1) == a_pos) or ((xb == 1) == b_pos)
                vals.append('1' if (xy == 1) == o else '0')
            factors.append(((a_var, b_var, y), vals)); y_prev = y
        l_var, l_pos = abs(cl[-1]) - 1, cl[-1] > 0
        vals = []
        for xy, xl in product((0, 1), repeat=2):
            vals.append('1' if (xy == 1 or ((xl == 1) == l_pos)) else '0')
        factors.append(((y_prev, l_var), vals))
    clause_factor_start.append(len(factors)); clause_aux_start.append(next_var)
    total_vars = next_var
    table_entries = sum(len(v) for _, v in factors)
    assert table_entries == meta['converted_table_entries'], (table_entries, meta['converted_table_entries'])
    assert aux_total == meta['converted_auxiliary_vars']
    os.makedirs(os.path.dirname(os.path.abspath(uai_path)), exist_ok=True)
    with open(uai_path, 'w') as f:
        f.write('MARKOV\n%d\n' % total_vars)
        f.write(' '.join('2' for _ in range(total_vars)) + '\n')
        f.write('%d\n' % len(factors))
        for scope, _ in factors:
            f.write('%d %s\n' % (len(scope), ' '.join(map(str, scope))))
        f.write('\n')
        for _, vals in factors:
            f.write('%d\n%s\n' % (len(vals), ' '.join(vals)))
    with open(uai_path + '.evid', 'w') as f:
        f.write('0\n')
    uai_bytes = open(uai_path, 'rb').read()
    side = dict(schema='CQR_WCNF_TO_UAI_CONVERSION_V1', name=name or os.path.basename(cnf_path), source_cnf=os.path.abspath(cnf_path),
                source_cnf_sha256=meta['cnf_sha256'], source_cnf_bytes=meta['cnf_bytes'], uai_path=os.path.abspath(uai_path),
                uai_sha256=hashlib.sha256(uai_bytes).hexdigest(), uai_bytes=len(uai_bytes), evidence='0 (empty evidence file)',
                rule=dict(variables='CNF var i (1..n) -> UAI var i-1, cardinality 2, state 1 = true; auxiliaries are UAI vars n.. in creation order',
                          unary='factor index i-1 over var i-1 with table [w(-i), w(+i)]; missing weight -> "1"',
                          short_clause='effective length k<=3: one factor over the distinct clause variables (scope order = first-seen literal order), value 1 iff satisfied',
                          long_clause='effective length k>3: y_1 = l_1 v l_2 ; y_j = y_{j-1} v l_{j+1} ; final factor 1[y_{k-2} v l_k]; each gate factor over (input_a, input_b, y) valued 1 iff y == (a v b) under the literal signs',
                          tautology='clause containing x and -x is dropped (always satisfied)', empty_clause='unary all-zero factor over var 0',
                          table_order='row-major over the listed scope order, as read by cex/newarm/core.py read_uai'),
                n_original_vars=n, n_auxiliary_vars=aux_total, n_total_vars=total_vars, n_factors=len(factors), table_entries=table_entries,
                m_header=meta['m_header'], n_clauses=len(clauses), dropped_tautological_clauses=dropped_tautologies,
                missing_weight_literals_defaulted_to_1=missing,
                clause_factor_map=dict(description='factors of clause c (0-based) are indices clause_factor_start[c] .. clause_factor_start[c+1]-1 (unary factors are indices 0..n-1); its auxiliary variables are clause_aux_start[c] .. clause_aux_start[c+1]-1',
                                       clause_factor_start=clause_factor_start, clause_aux_start=clause_aux_start),
                original_literal_weights={str(l): _frac_str(w) for l, w in sorted(weights.items(), key=lambda kv: (abs(kv[0]), kv[0]))},
                scan_metadata=meta)
    with open(uai_path + '.conversion.json', 'w') as f:
        json.dump(side, f, indent=0, sort_keys=False)
    return side


class CapExceeded(Exception):
    pass


# ----------------------------------------------------------------------------------------------------------------------
# brute force (certificate only; tiny problems)

def wmc_direct(n, clauses, weights):
    """weighted count straight from the CNF: sum over all 2^n assignments of prod literal weights * [all clauses satisfied]"""
    W = {}
    for v in range(1, n + 1):
        W[v] = Fraction(_frac_str(weights.get(v, '1'))); W[-v] = Fraction(_frac_str(weights.get(-v, '1')))
    total = Fraction(0)
    for x in product((0, 1), repeat=n):
        ok = True
        for cl in clauses:
            if cl is None:
                continue
            if not any(lit_true(l, x) for l in cl):
                ok = False; break
        if not ok:
            continue
        w = Fraction(1)
        for v in range(1, n + 1):
            w *= W[v] if x[v - 1] == 1 else W[-v]
        total += w
    return total


def uai_partition_bruteforce(model):
    cards = model['cards']; z = Fraction(0)
    for x in product(*(range(d) for d in cards)):
        if any(x[v] != a for v, a in model.get('evidence', {}).items()):
            continue
        w = Fraction(1)
        for f in model['factors']:
            i = 0
            for v in f['scope']:
                i = i * cards[v] + x[v]
            w *= f['values'][i]
            if w == 0:
                break
        z += w
    return z


def pointwise_check(model, n_orig, clauses, weights, assignments, max_aux_flips=None, seed=0):
    """for each original assignment x: the UNIQUE nonzero auxiliary completion has product == CNF weight of x.
    Auxiliaries are recomputed from the gate semantics (chain order of creation), then every single-aux flip is
    shown to give product 0.  Not inference: only evaluates products at given assignments."""
    cards = model['cards']; W = {}
    for v in range(1, n_orig + 1):
        W[v] = Fraction(_frac_str(weights.get(v, '1'))); W[-v] = Fraction(_frac_str(weights.get(-v, '1')))
    def prod_at(x):
        w = Fraction(1)
        for f in model['factors']:
            i = 0
            for v in f['scope']:
                i = i * cards[v] + x[v]
            val = f['values'][i]
            w *= Fraction(val) if isinstance(val, str) else val
            if w == 0:
                return w
        return w
    checked = 0
    for xo in assignments:
        x = list(xo) + [0] * (len(cards) - n_orig); nxt = n_orig
        for cl in clauses:
            if cl is None or len(cl) <= 3:
                continue
            prev = None
            for j in range(len(cl) - 2):
                a = lit_true(cl[0], x) if j == 0 else x[prev] == 1
                b = lit_true(cl[j + 1], x)
                x[nxt] = 1 if (a or b) else 0; prev = nxt; nxt += 1
        assert nxt == len(cards)
        direct = Fraction(1)
        for v in range(1, n_orig + 1):
            direct *= W[v] if x[v - 1] == 1 else W[-v]
        if any(cl is not None and not any(lit_true(l, x) for l in cl) for cl in clauses):
            direct = Fraction(0)
        got = prod_at(x)
        assert got == direct, (xo, got, direct)
        if got != 0:
            auxs = list(range(n_orig, len(cards)))
            if max_aux_flips is not None and len(auxs) > max_aux_flips:
                import random
                auxs = random.Random(seed).sample(auxs, max_aux_flips)
            for a in auxs:
                y = list(x); y[a] ^= 1
                assert prod_at(y) == 0, ('auxiliary not determined', a)
        checked += 1
    return checked


def read_uai_light(path):
    """Structural reader for large converted models: same token grammar as cex/newarm/core.py read_uai but table
    values are kept as strings (converted to Fraction only where a product is evaluated).  Asserts the header,
    scope and table-size consistency of the written file.  Not inference."""
    toks = open(path, 'rb').read().split(); it = iter(toks)
    kind = next(it).decode(); assert kind == 'MARKOV'
    n = int(next(it)); cards = [int(next(it)) for _ in range(n)]; assert all(c == 2 for c in cards)
    nf = int(next(it)); scopes = []
    for _ in range(nf):
        k = int(next(it)); sc = tuple(int(next(it)) for _ in range(k)); assert len(set(sc)) == k and all(0 <= v < n for v in sc); scopes.append(sc)
    factors = []
    for sc in scopes:
        k = int(next(it)); assert k == 2 ** len(sc), (k, sc)
        factors.append(dict(scope=sc, values=[next(it).decode() for _ in range(k)]))
    assert next(it, None) is None
    return dict(cards=cards, factors=factors, evidence={}), dict(n_vars=n, n_factors=nf, table_entries=sum(len(f['values']) for f in factors), model_sha256=hashlib.sha256(open(path, 'rb').read()).hexdigest())


def certificate(cnf_path, uai_path, read_uai):
    """Enumerate all original assignments (n <= 12) -> direct weighted count; brute-force Z of the written UAI
    model (read back through the repo reader); assert equality.  Returns the recorded pair."""
    meta, clauses, weights = scan_wcnf(cnf_path, keep_clauses=True)
    n = meta['n_vars']
    if n > 12:
        raise ValueError('certificate only for n <= 12 original variables (n=%d)' % n)
    model, info = read_uai(uai_path)
    direct = wmc_direct(n, clauses, weights); z = uai_partition_bruteforce(model)
    assert direct == z, (direct, z)
    return dict(n_original_vars=n, n_total_vars=len(model['cards']), wmc_direct=str(direct), uai_Z_bruteforce=str(z), equal=True,
                wmc_direct_float=float(direct), uai_sha256=info['model_sha256'])


# ----------------------------------------------------------------------------------------------------------------------
# synthetic unit tests

def _write(path, text):
    with open(path, 'w') as f:
        f.write(text)


def selftest(outdir, read_uai):
    """Three declared synthetic tests (long clause; unsatisfiable -> Z = 0; weighted small CNF) plus a random
    battery and a negative-weight refusal control.  Each test = conversion + certificate (n <= 12)."""
    import random
    os.makedirs(outdir, exist_ok=True); results = []
    # 1. a single long clause (k = 7) with unit weights: Z = 2^7 - 1 = 127
    t1 = 'c t wmc\np cnf 7 1\n' + ''.join('c p weight %d 1 0\nc p weight -%d 1 0\n' % (v, v) for v in range(1, 8)) + '1 -2 3 -4 5 -6 7 0\n'
    # 2. unsatisfiable: (x1 v x2) (-x1 v x2) (x1 v -x2) (-x1 v -x2) plus a long clause and weights -> Z = 0
    t2 = 'c t wmc\np cnf 5 5\n' + ''.join('c p weight %d 0.3 0\nc p weight -%d 0.7 0\n' % (v, v) for v in range(1, 6)) + '1 2 0\n-1 2 0\n1 -2 0\n-1 -2 0\n1 2 3 4 5 0\n'
    # 3. weighted small CNF: 6 vars, mixed lengths incl. k = 4 and k = 5, a repeated literal and a tautology
    t3 = ('c t wmc\np cnf 6 5\n' + ''.join('c p weight %d %s 0\nc p weight -%d %s 0\n' % (v, w, v, nw) for v, (w, nw) in
          enumerate([('0.25', '0.75'), ('0.5', '0.5'), ('1/3', '2/3'), ('0.9', '0.1'), ('2', '3'), ('0.125', '0.875')], start=1))
          + '1 -2 3 4 0\n-3 5 -6 1 2 0\n2 -4 0\n5 5 -6 0\n1 -1 6 0\n')
    tests = [('synthetic_long_clause', t1, Fraction(127)), ('synthetic_unsat_zero', t2, Fraction(0)), ('synthetic_weighted_small', t3, None)]
    for name, text, expect in tests:
        cp = os.path.join(outdir, name + '.cnf'); up = os.path.join(outdir, name + '.uai'); _write(cp, text)
        side = convert(cp, up, name=name); cert = certificate(cp, up, read_uai)
        if expect is not None:
            assert Fraction(cert['wmc_direct']) == expect, (name, cert['wmc_direct'], expect)
        meta, clauses, weights = scan_wcnf(cp, keep_clauses=True); model, _ = read_uai(up)
        rnd = random.Random(7); pts = [tuple(rnd.randint(0, 1) for _ in range(meta['n_vars'])) for _ in range(16)]
        pw = pointwise_check(model, meta['n_vars'], clauses, weights, pts)
        results.append(dict(test=name, certificate=cert, expected=(str(expect) if expect is not None else 'none (equality only)'),
                            auxiliary_vars=side['n_auxiliary_vars'], factors=side['n_factors'], pointwise_assignments_checked=pw, status='PASS'))
    # random battery: 20 random weighted CNFs with n <= 8, clause lengths 1..6
    rnd = random.Random(20261115); battery = 0
    for t in range(20):
        n = rnd.randint(2, 8); m = rnd.randint(1, 8); lines = ['c t wmc', 'p cnf %d %d' % (n, m)]
        for v in range(1, n + 1):
            a = rnd.randint(0, 9); lines.append('c p weight %d 0.%d 0' % (v, a)); lines.append('c p weight -%d 0.%d 0' % (v, 9 - a))
        for _ in range(m):
            k = rnd.randint(1, min(6, n + 1)); lines.append(' '.join(str(rnd.choice([-1, 1]) * rnd.randint(1, n)) for _ in range(k)) + ' 0')
        name = 'synthetic_random_%02d' % t; cp = os.path.join(outdir, name + '.cnf'); up = os.path.join(outdir, name + '.uai')
        _write(cp, '\n'.join(lines) + '\n'); convert(cp, up, name=name); certificate(cp, up, read_uai); battery += 1
    results.append(dict(test='synthetic_random_battery', cases=battery, status='PASS'))
    # parser refusal control: a negative weight must be refused, a non-rational token too
    for name, w in (('control_negative_weight', '-0.5'), ('control_nonrational_weight', 'inf')):
        cp = os.path.join(outdir, name + '.cnf'); _write(cp, 'c t wmc\np cnf 2 1\nc p weight 1 %s 0\nc p weight -1 0.5 0\nc p weight 2 1 0\nc p weight -2 1 0\n1 2 0\n' % w)
        meta = scan_wcnf(cp); assert meta['weight_status'] == 'REFUSED_NEGATIVE_OR_NONRATIONAL_WEIGHT', meta['weight_status']
        try:
            convert(cp, os.path.join(outdir, name + '.uai'), name=name); raise AssertionError('conversion must refuse')
        except ValueError as ex:
            results.append(dict(test=name, status='REFUSED_AS_REQUIRED', detail=str(ex)[:120], refused_weights=meta['refused_weights']))
    # cap control
    try:
        convert(os.path.join(outdir, 'synthetic_long_clause.cnf'), os.path.join(outdir, 'cap_control.uai'), cap_entries=10); raise AssertionError('cap must trigger')
    except CapExceeded as ex:
        results.append(dict(test='control_conversion_cap', status='CAP_REFUSED_AS_REQUIRED', computed_entries=ex.args[0], cap=10))
    return results
