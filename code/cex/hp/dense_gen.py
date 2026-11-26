"""Frozen generator of the DENSE_GENERIC_PAC_INTEGRATION_1 panels (brief CLAUDE_DENSE_GENERIC_PAC_INTEGRATION.md, 24 Nov 2026, section 8). Deterministic; two SEPARATE seed domains:
evaluation tag DENSE-GENERIC-PAC-EVAL-1 (24 holdout models, generated only after the implementation / calibration freeze) and development tag DENSE-GENERIC-PAC-DEV-1 (smaller
instances from the same recipe + boundary cases). Per-input seed = first eight SHA-256 bytes (big-endian) of '<tag>|<n>|<card>|<topology>|<scale>' feeding random.Random; the graph,
the pair tables and the unary fields draw from that one stream in the fixed order graph -> unary(v = 0..n-1) -> pair(edge in sorted order).
Panel (evaluation): n in {32, 64} x card in {2, 4} x topology in {reg6 = connected 6-regular, er50 = connected Erdos-Renyi p = 1/2, clique = complete} x scale in {1/2, 2}, lexicographic.
Graphs: reg6 by the sequential pairing procedure (Steger-Wormald style: n d points, repeatedly match two uniformly chosen unmatched points of distinct, non-adjacent vertices; a dead end
restarts the attempt); er50 includes each pair independently with probability exactly 1/2 (one randrange(2) per pair in sorted pair order); clique = all pairs. Every attempt that is a dead
end or disconnected (BFS) is REJECTED and counted (graph_attempts); the first connected graph is kept. Pair table for edge (u, v), u < v, row-major over (a, b): raw entries k / 2^12 with
k uniform in [-2^12, 2^12]; the matrix is double-centred exactly (entry - row mean - column mean + grand mean); beta = scale / sqrt(mean degree of the generated graph) (one float);
ideal entry exp(beta * centred) computed once in double precision; the SERIALIZED entry is the nearest positive integer multiple of 2^-24, ties rounded up, minimum 2^-24. Unary field
h_v(a) = the same rounding of exp(u / 10) with u uniform on the k / 2^12 grid in [-1, 1]. The serialized rationals DEFINE the model; nothing assumes the rounded model equals an ideal
exponential family. No evidence; the request is every singleton coordinate (K = n card). Disclosures per input: degrees, cycle rank E - n + 1, entries, dynamic range, and the actual
exact-profile reduction found by the unchanged coarse_envelope.exact_profile_classes (an incidental reduction is disclosed, never grounds to replace the input).
Development panel: n in {8, 12} x card in {2, 4} x the three topologies x scale in {1/2, 2} (24) + boundary cases (near-product scale 1/8: n 8 c2 er50, n 8 c4 clique; strong frustrated
scale 4: n 8 c2 clique, n 8 c2 reg6); exact-enumeration oracle eligibility card^n <= 2^16 recorded.
usage: dense_gen.py eval|dev|devmid|oracle_eval|oracle_dev|eval2|eval3|...|eval7|oracle7 OUTDIR  (DGP2 tags: DGP2-ORACLE-EVAL-1 / DGP2-ORACLE-DEV-1 / DENSE-GENERIC-PAC-EVAL-2; DGP3: DENSE-GENERIC-PAC-EVAL-3; DGP7: prefixes DGP7/EVAL7/ and DGP7/ORACLE7/ with the canonical-JSON seed rule, ORACLE7 carrying an integer `variant` 0 / 1 (dgp7_seed_record); the table / unary recipe is UNCHANGED)"""
import sys, os, json, hashlib, random, math, argparse, time
from fractions import Fraction as F
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
TAG_EVAL = 'DENSE-GENERIC-PAC-EVAL-1'; TAG_DEV = 'DENSE-GENERIC-PAC-DEV-1'
GRID = 1 << 12; ROUND_BITS = 24; UNARY_SCALE = F(1, 10); MAX_GRAPH_ATTEMPTS = 10000; ORACLE_CAP = 1 << 16
TOPOS = ('reg6', 'er50', 'clique'); SCALE_NAME = {F(1, 2): 'half', F(2): 'two', F(1, 8): 'eighth', F(4): 'four'}


def dgp6_canonical_json(n, card, topo, scale):
    """the canonical sorted JSON of (family, n, card, coupling): keys sorted, no spaces, coupling as its exact rational string ('1/2' | '2'), family as 'ER' | 'clique'"""
    import json
    return json.dumps(dict(card=int(card), coupling=str(F(scale)), family={'er50': 'ER', 'clique': 'clique'}[topo], n=int(n)), sort_keys=True, separators=(',', ':'))
def dgp6_seed_record(tag, n, card, topo, scale):
    key = tag + dgp6_canonical_json(n, card, topo, scale); x = int.from_bytes(hashlib.sha256(key.encode('utf-8')).digest()[:8], 'big'); return dict(prefix=tag, canonical_json=dgp6_canonical_json(n, card, topo, scale), seed_string=key, sha256_first8_big_endian=x, seed=x % ((1 << 31) - 1), rule="int.from_bytes(SHA256(prefix + canonical sorted JSON of family, n, card, coupling)[:8], 'big') mod (2^31 - 1)")
def dgp7_canonical_json(n, card, topo, scale, variant=None):
    """DGP7 (PROTOCOL section 3): the canonical sorted JSON of (card, coupling, family, n[, variant]) -- keys sorted, no spaces, coupling as its exact rational string ('1/2' | '2'), family 'ER' | 'clique'; `variant` (0 | 1) only for the
    ORACLE7 panel (two strong cliques + two strong ER50 at n 8 from the same recipe)"""
    import json
    d = dict(card=int(card), coupling=str(F(scale)), family={'er50': 'ER', 'clique': 'clique'}[topo], n=int(n))
    if variant is not None: d['variant'] = int(variant)
    return json.dumps(d, sort_keys=True, separators=(',', ':'))
def dgp7_seed_record(tag, n, card, topo, scale, variant=None):
    key = tag + dgp7_canonical_json(n, card, topo, scale, variant); x = int.from_bytes(hashlib.sha256(key.encode('utf-8')).digest()[:8], 'big'); return dict(prefix=tag, canonical_json=dgp7_canonical_json(n, card, topo, scale, variant), seed_string=key, sha256_first8_big_endian=x, seed=x % ((1 << 31) - 1), variant=variant, rule="int.from_bytes(SHA256(prefix + canonical sorted JSON {card, coupling, family, n[, variant]})[:8], 'big') mod (2^31 - 1)")
def seed_of(tag, n, card, topo, scale, variant=None):
    """per-input seed: first eight SHA-256 bytes (unsigned big-endian) of the UTF-8 tag string feeding random.Random. DGP1-3 tags: '<tag>|<n>|<card>|<topo>|<scale>'. DGP4 tags (brief section 6 / 7, verbatim):
    'DGP4-EVAL4|<n>|<topology>|<coupling>|c4' and 'DGP4-ORACLE4|<n>|<topology>|<coupling>|c4' with topology in {ER, clique} and coupling the rational string ('1/2', '2')"""
    if tag in ('DGP4-EVAL4', 'DGP4-ORACLE4', 'DGP5-EVAL5'):
        assert card == 4; key = '%s|%d|%s|%s|c4' % (tag, n, {'er50': 'ER', 'clique': 'clique'}[topo], str(F(scale)))
    elif tag == 'DGP5-ORACLE5':                                                                         # DGP5 brief section 12: 'DGP5-ORACLE5|n|topology|two|c4' (coupling 2 written as the word 'two')
        assert card == 4 and F(scale) == 2; key = '%s|%d|%s|two|c4' % (tag, n, {'er50': 'ER', 'clique': 'clique'}[topo])
    elif tag in ('DGP7/EVAL7/', 'DGP7/ORACLE7/'):                                                      # DGP7 PROTOCOL section 3: the DGP6 JSON rule with the DGP7 prefixes; ORACLE7 adds the integer `variant` key (recorded by dgp7_seed_record)
        key = tag + dgp7_canonical_json(n, card, topo, scale, variant); return int.from_bytes(hashlib.sha256(key.encode('utf-8')).digest()[:8], 'big') % ((1 << 31) - 1)
    elif tag in ('DGP6/EVAL6/', 'DGP6/ORACLE6/'):                                                      # DGP6 brief section 6: int.from_bytes(SHA256(prefix + canonical sorted JSON of family, n, card, coupling)[:8], 'big') mod (2^31 - 1); the JSON string is recorded by dgp6_seed_record
        key = tag + dgp6_canonical_json(n, card, topo, scale); return int.from_bytes(hashlib.sha256(key.encode('utf-8')).digest()[:8], 'big') % ((1 << 31) - 1)
    else: key = '%s|%d|%d|%s|%s' % (tag, n, card, topo, scale)
    return int.from_bytes(hashlib.sha256(key.encode('utf-8')).digest()[:8], 'big')


def connected(n, edges):
    adj = [[] for _ in range(n)]
    for u, v in edges: adj[u].append(v); adj[v].append(u)
    seen = {0}; stack = [0]
    while stack:
        x = stack.pop()
        for y in adj[x]:
            if y not in seen: seen.add(y); stack.append(y)
    return len(seen) == n


def regular_attempt(rng, n, d):
    """one sequential-pairing attempt; returns the edge list or None at a dead end"""
    pts = [v for v in range(n) for _ in range(d)]; adj = set(); edges = []
    while pts:
        pick = None
        for _ in range(256):
            i = rng.randrange(len(pts)); j = rng.randrange(len(pts))
            if i == j: continue
            u, v = pts[i], pts[j]
            if u == v or (min(u, v), max(u, v)) in adj: continue
            pick = (i, j); break
        if pick is None:
            cands = [(i, j) for i in range(len(pts)) for j in range(i + 1, len(pts)) if pts[i] != pts[j] and (min(pts[i], pts[j]), max(pts[i], pts[j])) not in adj]
            if not cands: return None
            pick = cands[rng.randrange(len(cands))]
        i, j = pick; u, v = pts[i], pts[j]; e = (min(u, v), max(u, v)); adj.add(e); edges.append(e)
        for k in sorted((i, j), reverse=True): pts.pop(k)
    return sorted(edges)


def graph(rng, topo, n):
    """-> (sorted edge list, rejected attempts, reasons)"""
    rejected = 0; reasons = dict(dead_end=0, disconnected=0)
    for _ in range(MAX_GRAPH_ATTEMPTS):
        if topo == 'reg6': E = regular_attempt(rng, n, 6)
        elif topo == 'er50': E = [(u, v) for u in range(n) for v in range(u + 1, n) if rng.randrange(2) == 1]
        elif topo == 'clique': E = [(u, v) for u in range(n) for v in range(u + 1, n)]
        else: raise ValueError(topo)
        if E is None: rejected += 1; reasons['dead_end'] += 1; continue
        if not connected(n, E): rejected += 1; reasons['disconnected'] += 1; continue
        return E, rejected, reasons
    raise RuntimeError('no connected %s graph on %d vertices in %d attempts' % (topo, n, MAX_GRAPH_ATTEMPTS))


def raw(rng): return F(rng.randint(-GRID, GRID), GRID)


def double_center(Mx):
    k = len(Mx); rows = [sum(r) / k for r in Mx]; cols = [sum(Mx[a][b] for a in range(k)) / k for b in range(k)]; g = sum(rows) / k
    return [[Mx[a][b] - rows[a] - cols[b] + g for b in range(k)] for a in range(k)]


def round_pos(x):
    """nearest positive integer multiple of 2^-ROUND_BITS of the double x; ties up; minimum one grid unit"""
    q = F(x) * (1 << ROUND_BITS); k = math.floor(q + F(1, 2)); return F(max(1, k), 1 << ROUND_BITS)


def build(tag, n, card, topo, scale, variant=None):
    rng = random.Random(seed_of(tag, n, card, topo, scale, variant)); E, rejected, reasons = graph(rng, topo, n); mean_deg = 2.0 * len(E) / n; beta = float(scale) / math.sqrt(mean_deg)
    unaries = [[round_pos(math.exp(float(UNARY_SCALE * raw(rng)))) for _ in range(card)] for _ in range(n)]
    pairs = []
    for (u, v) in E:
        C = double_center([[raw(rng) for _ in range(card)] for _ in range(card)]); pairs.append([round_pos(math.exp(beta * float(C[a][b]))) for a in range(card) for b in range(card)])
    model = dict(cards=[card] * n, factors=[dict(scope=(v,), values=unaries[v]) for v in range(n)] + [dict(scope=E[i], values=pairs[i]) for i in range(len(E))], evidence={})
    deg = [0] * n
    for u, v in E: deg[u] += 1; deg[v] += 1
    allp = [x for t in pairs for x in t]; allu = [x for t in unaries for x in t]
    rec = dict(n=n, card=card, topology=topo, scale=str(scale), beta=beta, edges=len(E), degree=dict(min=min(deg), max=max(deg), mean=mean_deg), cycle_rank=len(E) - n + 1, graph_attempts_rejected=rejected, graph_rejection_reasons=reasons,
               entries=dict(pair=len(allp), unary=len(allu), total=len(allp) + len(allu)), dynamic_range=dict(pair_max=str(max(allp)), pair_min=str(min(allp)), pair_log10=math.log10(float(max(allp) / min(allp))), unary_max=str(max(allu)), unary_min=str(min(allu))),
               oracle_eligible=(card ** n <= ORACLE_CAP), K=n * card)
    if variant is not None: rec['variant'] = int(variant)
    return model, rec


def exact_reduction(model):
    """disclosure: variables whose states the unchanged exact profile quotient merges (incidental reductions)"""
    import coarse_envelope as CE
    clk = CE.Clock(CE.tnow() + 60.0, {}); B = CE.Budget(CE.CONSTRUCTOR_BYTES); M = CE.canonicalize(model, clk, B)
    try: classes = CE.exact_profile_classes(M, clk, B)
    except CE.Refused as e: return dict(status='REFUSED_' + e.kind)
    red = [(int(M.orig_of[v]), len(set(classes[v]))) for v in range(len(M.cards)) if len(set(classes[v])) < M.cards[v]]
    return dict(variables_reduced=len(red), detail=red[:16], retained_variables=len(M.cards), zero_mass=M.zero_mass)


TAG_ORACLE_EVAL = 'DGP2-ORACLE-EVAL-1'; TAG_ORACLE_DEV = 'DGP2-ORACLE-DEV-1'; TAG_EVAL2 = 'DENSE-GENERIC-PAC-EVAL-2'; TAG_EVAL3 = 'DENSE-GENERIC-PAC-EVAL-3'; TAG_EVAL4 = 'DGP4-EVAL4'; TAG_ORACLE4 = 'DGP4-ORACLE4'; TAG_EVAL5 = 'DGP5-EVAL5'; TAG_ORACLE5 = 'DGP5-ORACLE5'; TAG_EVAL6 = 'DGP6/EVAL6/'; TAG_ORACLE6 = 'DGP6/ORACLE6/'; TAG_EVAL7 = 'DGP7/EVAL7/'; TAG_ORACLE7 = 'DGP7/ORACLE7/'
DGP4_TAGS = (TAG_EVAL4, TAG_ORACLE4)


def panel(kind):
    if kind == 'oracle_eval': return TAG_ORACLE_EVAL, [(n, c, t, s) for (n, c) in ((8, 2), (12, 2), (6, 4), (8, 4)) for t in ('er50', 'clique') for s in (F(1, 2), F(2))]           # DGP2 brief section 4: 16 oracle inputs, each <= 2^16 fine states
    if kind == 'oracle_dev': return TAG_ORACLE_DEV, [(n, c, t, s) for (n, c) in ((6, 2), (8, 2), (5, 4), (6, 4)) for t in ('er50', 'clique') for s in (F(1, 2), F(2))]
    if kind == 'eval7': return TAG_EVAL7, [(n, 4, t, s) for n in (32, 64) for t in ('er50', 'clique') for s in (F(1, 2), F(2))]                                                           # DGP7 PROTOCOL section 3: 8 fresh production inputs (unchanged recipe; seed domain DGP7/EVAL7/ + canonical JSON)
    if kind == 'oracle7': return TAG_ORACLE7, [(8, 4, t, F(2), v) for t in ('clique', 'er50') for v in (0, 1)]                                                                           # DGP7 PROTOCOL section 3: 4 fresh strong n8 card-4 coupling-2 oracle models (two cliques, two ER50) by the `variant` key 0 / 1
    if kind == 'eval6': return TAG_EVAL6, [(n, 4, t, s) for n in (32, 64) for t in ('er50', 'clique') for s in (F(1, 2), F(2))]                                                           # DGP6 brief section 6: 8 fresh production inputs (unchanged generator recipe; new seed domain DGP6/EVAL6/ + canonical JSON)
    if kind == 'oracle6': return TAG_ORACLE6, [(n, 4, t, F(2)) for n in (6, 8) for t in ('er50', 'clique')]                                                                                  # DGP6 brief section 6: 4 fresh strong small oracle models (coupling 2 only)
    if kind == 'eval5': return TAG_EVAL5, [(n, 4, t, s) for n in (32, 64) for t in ('er50', 'clique') for s in (F(1, 2), F(2))]                                                           # DGP5 brief section 12: 8 fresh production inputs (seed string DGP5-EVAL5|n|ER/clique|coupling|c4; recipe unchanged)
    if kind == 'oracle5': return TAG_ORACLE5, [(n, 4, t, F(2)) for n in (6, 8) for t in ('er50', 'clique')]                                                                                  # DGP5 brief section 12: 4 fresh strong small oracle models (coupling 2 only)
    if kind == 'eval4': return TAG_EVAL4, [(n, 4, t, s) for n in (32, 64) for t in ('er50', 'clique') for s in (F(1, 2), F(2))]                                                           # DGP4 brief section 6: 8 fresh production inputs (seed string DGP4-EVAL4|n|ER/clique|coupling|c4; recipe unchanged)
    if kind == 'oracle4': return TAG_ORACLE4, [(n, 4, t, s) for n in (6, 8) for t in ('er50', 'clique') for s in (F(1, 2), F(2))]                                                        # DGP4 brief section 7: 8 fresh small oracle models
    if kind == 'eval3': return TAG_EVAL3, [(n, 4, t, s) for n in (32, 64) for t in ('er50', 'clique') for s in (F(1, 2), F(2))]                                                           # DGP3 PROTOCOL section 3: 8 fresh production inputs (new tag -> new seed domain; recipe unchanged)
    if kind == 'eval2': return TAG_EVAL2, [(n, 4, t, s) for n in (32, 64) for t in ('er50', 'clique') for s in (F(1, 2), F(2))]                                                           # DGP2 brief section 5: 8 fresh production inputs
    if kind == 'devmid': return TAG_DEV, [(n, c, t, F(2)) for n in (16, 20, 24) for c in (2, 4) for t in TOPOS] + [(20, 2, 'er50', F(1, 2)), (24, 2, 'clique', F(1, 2))]      # development: beyond the deterministic reach (PAC exercised), same recipe, dev seed domain
    if kind == 'eval': return TAG_EVAL, [(n, c, t, s) for n in (32, 64) for c in (2, 4) for t in TOPOS for s in (F(1, 2), F(2))]
    base = [(n, c, t, s) for n in (8, 12) for c in (2, 4) for t in TOPOS for s in (F(1, 2), F(2))]
    return TAG_DEV, base + [(8, 2, 'er50', F(1, 8)), (8, 4, 'clique', F(1, 8)), (8, 2, 'clique', F(4)), (8, 2, 'reg6', F(4))]


def generate(kind, outdir):
    import hp_gen as G
    tag, combos = panel(kind); os.makedirs(outdir, exist_ok=True); man = []
    for combo in combos:
        n, card, topo, scale = combo[:4]; variant = combo[4] if len(combo) > 4 else None
        model, rec = build(tag, n, card, topo, scale, variant); name = 'dg_n%d_c%d_%s_%s' % (n, card, topo, SCALE_NAME[scale]) + ('_v%d' % variant if variant is not None else ''); p = os.path.join(outdir, name + '.uai'); G.write(p, model)
        rec.update(name=name, tag=tag, seed=seed_of(tag, n, card, topo, scale, variant), seed_record=(dgp6_seed_record(tag, n, card, topo, scale) if tag.startswith('DGP6/') else dgp7_seed_record(tag, n, card, topo, scale, variant) if tag.startswith('DGP7/') else None), model=os.path.abspath(p), model_sha256=hashlib.sha256(open(p, 'rb').read()).hexdigest(), evid_sha256=hashlib.sha256(open(p + '.evid', 'rb').read()).hexdigest(), exact_profile_reduction=exact_reduction(model))
        man.append(rec); print(name, rec['edges'], 'edges', 'rej', rec['graph_attempts_rejected'], 'reduced', rec['exact_profile_reduction'].get('variables_reduced'), rec['model_sha256'][:12], flush=True)
    json.dump(dict(kind=kind, tag=tag, generator_sha256=hashlib.sha256(open(__file__, 'rb').read()).hexdigest(), hp_gen_sha256=hashlib.sha256(open(os.path.join(HERE, 'hp_gen.py'), 'rb').read()).hexdigest(), constants=dict(GRID=GRID, ROUND_BITS=ROUND_BITS, UNARY_SCALE=str(UNARY_SCALE), MAX_GRAPH_ATTEMPTS=MAX_GRAPH_ATTEMPTS, ORACLE_CAP=ORACLE_CAP),
                   python=sys.version.split()[0], platform=sys.platform, utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), inputs=man, note='exp() is evaluated in double precision once per entry; the serialized rationals define the model; the sha256 of each file is the frozen identity (regeneration on another libm may differ in the last bit)'), open(os.path.join(outdir, 'GENERATED_MANIFEST.json'), 'w'), indent=1)
    return man


if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('kind', choices=['eval', 'dev', 'devmid', 'oracle_eval', 'oracle_dev', 'eval2', 'eval3', 'eval4', 'oracle4', 'eval5', 'oracle5', 'eval6', 'oracle6', 'eval7', 'oracle7']); ap.add_argument('outdir'); a = ap.parse_args(); generate(a.kind, a.outdir)
