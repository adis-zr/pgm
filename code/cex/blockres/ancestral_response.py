"""NORMALIZED ANCESTRAL RESPONSES (round 22, 23 Nov 2026; THEOREMS.md + CLAUDE_IMPLEMENTATION_BRIEF.md of the R22 packet).

A normalized part of a model (founder priors, exact multiplexer conditionals, uniformly started symmetric binary selector paths) contributes only a scalar to the normalizer, yet its
original singleton queries still depend on the retained core. This constructor (1) recognises the roles by EXACT table identities on the original model -- multiplexer: one child, two
same-domain parents, a binary selector, child = parent[selector] entrywise; founder: an allele with no defining multiplexer, its unary occurrences multiplied exactly (empty product = the
implicit weight 1 per state); selector path: disjoint symmetric stochastic binary channels [t, 1-t; 1-t, t] starting at exactly one explicit uniform [1/2, 1/2] prior; everything else is an
OPAQUE residual (a unary likelihood on a multiplexer child included); (2) retains every allele of an opaque factor or of evidence plus its full parental ancestor closure, the selectors
those retained multiplexers and residuals need, and on every recognised path the suffix from the earliest needed node (a path with no needed node keeps its last node as a proxy); the
erased prefix is replaced by a uniform prior at the retained boundary; (3) compiles the conditional response of every removed allele state as a sparse affine Walsh polynomial in terms
(retained root, state, selector subset) -> Fraction (g_child = (g_p0 + g_p1)/2 + chi_sel (g_p0 - g_p1)/2; symmetric-difference character products; retained alleles are kept as indicators,
never replaced by their priors), transports erased-prefix characters to the boundary by the XOR-of-edge-paths rule (rho_e = 2 theta_e - 1 per edge traversed an odd number of times; negative
and zero rho valid); removed selectors use P(S=1) = (1 - rho E[chi_boundary]) / 2; (4) appends one normalized deterministic Boolean auxiliary per required pure parity (Y = xor(A)) or mixed
moment (Y = 1[X_r = a AND xor(A) = 1]) -- these sum to one pointwise so Z and retained marginals are preserved, and they are REAL sources in the physical plan; (5) orders the augmented
physical graph by the deterministic weighted minimum product (bucket product, output, degree, seed-0 tie) and certifies the complete bucket order's volumes exactly as the layered route
does; (6) runs the UNCHANGED certified native executor once through layered_contraction.execute (its typed stops, labels, Z enclosure x cancelled scalars incl. the appended erasure scalar
and the observed-bucket correction); (7) decodes every original coordinate by exact signed affine interval arithmetic over the executor's enclosures (E chi_A = 1 - 2 P(Y_A = 1);
E[1[X_r = a] chi_A] = P(X_r = a) - 2 P(Y = 1)), intersects with [0, 1], compacts outward on the 2^-52 grid, and chooses points inside the epsilon-safe J intervals when their product meets
the simplex (else interval midpoints). Scalars: erased founder masses c_v multiplied once (appended as one empty-scope factor the executor cancels and the adapter restores); original scalar
factors stay in the core once; a zero founder mass is a typed zero-mass refusal before any division.
Bounded (round 22b repair): ONE construction allowance anchored at its own start, polled inside the role scan, the unary products, the topological order, the ancestry closure, the
component discovery / path traversal / prefix witness, the sparse merges (per 1,024 terms), the transport (per 1,024 terms), the query-table generation (per 1,024 entries), the physical
graph source cliques and each fill (charged before allocation, including temporary sets), the order scoring (per 64 candidates and per 64 eliminations), the certificate, and before the plan is returned; the restriction helper's typed refusal is translated to this
module's RecognitionRefused. Storage: the path witness is COMPACT (one edge list per path, (path, position, cut) per removed node; edge parities by index ranges), charged with the selector
graph before the walk; merges, transported polynomials and the physical adjacency are charged BEFORE they are built; transport products and coefficients are bit-checked; guards on predicate
checks (2^20), live sparse terms (2^18, admitted before each merge), appended query entries (2^18), exact integer bits (8,192) and a named-container estimate (128 MiB); typed refusals (NotApplicable /
RecognitionRefused / ResourceRefused / ZeroMass) fall back; the decode polls per variable and guards before the result is returned. Cooperative: one exact Fraction operation is not
interruptible; the supervisor is the hard bound. No model name, hash, variable id pattern, locus count, supplied partition, order or decoder is an admission rule."""
import os, sys, time, math, json
from fractions import Fraction as F
from itertools import product as iproduct, permutations
from collections import defaultdict, Counter
HERE = os.path.dirname(os.path.abspath(__file__)); NEWARM = os.path.join(os.path.dirname(os.path.dirname(HERE)), 'cex', 'newarm')
if NEWARM not in sys.path: sys.path.insert(0, NEWARM)
import layered_contraction as LC

MAX_PREDICATE_CHECKS = 1 << 20      # exact table-entry comparisons in the role scan (early exit per failed role)
MAX_LIVE_TERMS = 1 << 18            # simultaneously live sparse response terms
MAX_QUERY_ENTRIES = 1 << 18         # total appended query-table entries
MAX_INT_BITS = 8192                 # bits of any newly constructed exact integer (scalars, coefficients)
CONSTRUCTION_BYTES = 128 << 20      # named-container estimate of the construction (an estimate of named allocations, not a proven RSS bound)
TERM_BYTES = 320; ENTRY_BYTES = 48; ROW_BYTES = 1200; U = F(1, 1 << 53)
GRAPH_ENTRY_BYTES = 128             # includes conservative CPython set capacity slack; headers charged separately
def _term_cost(k): return TERM_BYTES + 8 * k        # one sparse term: dict slot + (root, state, subset) key tuple + a k-element subset tuple + the Fraction and its limbs (round 22b: the subset length is charged, wide Walsh keys were under-covered at a flat 200 B)


class NotApplicable(Exception): pass        # outside the recognised family / nothing to erase (typed refusal of this OPTIONAL route, never of the task)
class RecognitionRefused(Exception): pass   # construction allowance / global deadline exhausted
class ResourceRefused(Exception): pass      # a storage guard or the physical forecast refuses BEFORE allocation / execution
class ZeroMass(Exception): pass             # an exact zero founder mass: zero total mass, no division
class DeadlineRefused(Exception): pass      # deadline during decode / publication (nothing published)
ExecutorRefused = LC.ExecutorRefused; ZeroEvidence = LC.ZeroEvidence


def tnow(): return time.monotonic()


class Plan:
    __slots__ = ('aug', 'order', 'cancelled_scalar', 'cancelled_count', 'mapping', 'cards_orig', 'ev_orig', 'decoder', 'selector_transport', 'qvar', 'retained', 'removed_alleles', 'removed_selectors', 'scalar', 'volume', 'forecast', 'structure', 'recognition_s', 'binding', 'bytes_charged')


class Budget:
    def __init__(self, limit): self.limit = limit; self.charged = 0
    def charge(self, n, what):
        self.charged += int(n)
        if self.charged > self.limit: raise ResourceRefused('construction containers %d B > %d B (%s)' % (self.charged, self.limit, what))


def _bits_ok(x, what):
    if isinstance(x, F): n = max(x.numerator.bit_length(), x.denominator.bit_length())
    else: n = int(x).bit_length()
    if n > MAX_INT_BITS: raise ResourceRefused('%s needs %d bits > %d' % (what, n, MAX_INT_BITS))


def _mux_roles(f, cards, counter, poll):
    sc = f['scope']; vals = f['values']
    if len(sc) != 4 or any(x != 0 and x != 1 for x in vals): return []
    roles = []
    for ch, pa, pb, sel in permutations(sc):
        if cards[sel] != 2 or not (cards[ch] == cards[pa] == cards[pb] > 1): continue
        ix = {v: j for j, v in enumerate(sc)}; good = True
        for xs, w in zip(iproduct(*(range(cards[v]) for v in sc)), vals):
            counter[0] += 1
            if counter[0] > MAX_PREDICATE_CHECKS: raise ResourceRefused('role scan exceeds %d exact entry checks' % MAX_PREDICATE_CHECKS)
            if (counter[0] & 4095) == 0: poll('inside the role scan')
            if w != int(xs[ix[ch]] == xs[ix[pa if xs[ix[sel]] == 0 else pb]]): good = False; break
        if good: roles.append((ch, pa, pb, sel))
    return roles


def recognize(model, deadline=math.inf, binding=None, construction_s=1.0, byte_limit=CONSTRUCTION_BYTES, max_query_entries=MAX_QUERY_ENTRIES, max_live_terms=MAX_LIVE_TERMS):
    t0 = tnow(); dl = min(deadline, t0 + construction_s); cards = model['cards']; n = len(cards); ev = model.get('evidence', {}); facs = model['factors']; B = Budget(byte_limit)
    def poll(where):
        if tnow() >= dl: raise RecognitionRefused('construction allowance exhausted %s' % where)
    # ---- 1. roles by exact table identities (the per-variable / per-factor role tables are charged BEFORE the scan: unary, defs, opaque, mux_fid, kids, indeg, graph, chan)
    B.charge(n * 200 + len(facs) * 160, 'role tables (per variable and per factor)')
    counter = [0]; unary = {}; defs = defaultdict(list); opaque = []; mux_fid = {}
    for fi, f in enumerate(facs):
        if (fi & 63) == 63: poll('inside the role scan (factor %d)' % fi)
        roles = _mux_roles(f, cards, counter, poll)
        if roles:
            if len(roles) != 1: raise NotApplicable('factor %d admits %d multiplexer role assignments (ambiguous)' % (fi, len(roles)))
            ch, pa, pb, sel = roles[0]; defs[ch].append((pa, pb, sel, fi)); mux_fid[fi] = ch
        elif len(f['scope']) == 1: unary.setdefault(f['scope'][0], []).append(fi)
        else: opaque.append(fi)
    if not defs: raise NotApplicable('no exact multiplexer factor')
    for ch, ds in defs.items():
        if len(ds) != 1: raise NotApplicable('%d multiplexer factors define child %d' % (len(ds), ch))
    defs = {ch: ds[0] for ch, ds in defs.items()}; selectors = {d[2] for d in defs.values()}
    parents = {p for d in defs.values() for p in d[:2]}; children = set(defs)
    multi = set()
    for f in facs:
        if len(f['scope']) > 1: multi.update(f['scope'])
    unary_only = {v for v in unary if v not in selectors and v not in children and v not in multi}       # a variable whose every factor is unary: a childless founder (its mass is an exact scalar)
    founders = (parents | unary_only) - children                                                        # alleles: children + their parents + childless founders
    alleles = children | parents | unary_only
    if alleles & selectors: raise NotApplicable('overlapping allele and selector roles')
    # founder weights: exact products of ALL unary occurrences (empty product = implicit [1]*card); a unary on a non-founder allele is a likelihood -> opaque
    priors = {}; mass = {}
    for v in founders:
        poll('inside the founder products'); w = [F(1)] * cards[v]
        for fi in unary.get(v, ()):
            w = [x * y for x, y in zip(w, facs[fi]['values'])]
            for x in w: _bits_ok(x, 'founder weight')
        if any(x < 0 for x in w): raise NotApplicable('negative founder weight on %d' % v)
        z = sum(w)
        if z == 0: raise ZeroMass('founder %d has zero total weight' % v)
        priors[v] = [x / z for x in w]; mass[v] = z
    founder_unary = {fi for v in founders for fi in unary.get(v, ())}
    uniform = defaultdict(list)
    for v, fis in unary.items():
        if v in founders: continue
        for fi in fis:
            if v in selectors and facs[fi]['values'] == [F(1, 2), F(1, 2)]: uniform[v].append(fi)
            else: opaque.append(fi)                                                                       # child likelihoods, non-uniform selector priors, unaries on other variables
    # ---- 2. iterative topological order of the allele DAG (cycle -> refusal)
    indeg = {v: 0 for v in alleles}; kids = defaultdict(list)
    for ch, (pa, pb, s, fi) in defs.items():
        for p in (pa, pb): indeg[ch] += 1; kids[p].append(ch)
    order = [v for v in sorted(alleles) if indeg[v] == 0]; k = 0
    while k < len(order):
        if (k & 255) == 255: poll('inside the topological order')
        v = order[k]; k += 1
        for c in kids[v]:
            indeg[c] -= 1
            if indeg[c] == 0: order.append(c)
    if len(order) != len(alleles): raise NotApplicable('cyclic allele graph')
    # ---- 3. channel graph among selectors; opaque classification of the remaining factors
    chan = {}; graph = defaultdict(list); resid = []
    for fi in opaque:
        f = facs[fi]; sc = f['scope']; d = f['values']
        if len(sc) == 2 and sc[0] in selectors and sc[1] in selectors and len(d) == 4 and d[0] == d[3] and d[1] == d[2] and d[0] + d[1] == 1 and d[0] >= 0 and d[1] >= 0:
            chan[fi] = (sc[0], sc[1], d[0] - d[1]); graph[sc[0]].append((sc[1], fi)); graph[sc[1]].append((sc[0], fi)); continue
        resid.append(fi)
    poll('after the factor classification')
    # ---- 4. retention: residual / evidence alleles + ancestor closure; needed selectors
    seeds = set(ev)
    for fi in resid: seeds.update(facs[fi]['scope'])
    retainedA = seeds & alleles; todo = list(retainedA); k = 0
    while todo:
        if (k & 255) == 255: poll('inside the ancestry closure')
        k += 1; v = todo.pop()
        if v in defs:
            for p in defs[v][:2]:
                if p not in retainedA: retainedA.add(p); todo.append(p)
    needS = (seeds & selectors) | {defs[v][2] for v in retainedA if v in defs}
    # ---- 5. selector paths: uniform-rooted simple paths; cut before the earliest needed node (proxy = last node)
    removedS = set(); seen = set(); paths = []; transport = {}; path_edges = {}; node_pos = {}; edge_rho = {}; rho_at = {}; cut_of = {}; walked = 0
    B.charge(len(selectors) * 120 + len(chan) * 80, 'selector graph + path witness index (one entry per selector / channel)')      # the compact witness: per path ONE edge list; per removed node (path id, position); edge parities by index range
    for start in sorted(selectors):
        if start in seen: continue
        poll('inside the path walk'); comp = set(); stack = [start]
        while stack:
            walked += 1
            if (walked & 255) == 0: poll('inside the component discovery')
            v = stack.pop()
            if v in comp: continue
            comp.add(v); stack.extend(w for w, fi in graph[v] if w not in comp)
        seen |= comp
        ends = [v for v in comp if len(graph[v]) <= 1]; roots = [v for v in ends if len(uniform[v]) == 1]
        if not (len(roots) == 1 and len(ends) == 2 and all(len(graph[v]) <= 2 for v in comp) and sum(len(uniform[v]) for v in comp) == 1): paths.append(dict(status='retained', variables=len(comp))); continue
        seq = []; prev = None; v = roots[0]; eids = []
        while v is not None:
            if (len(seq) & 255) == 255: poll('inside the path traversal')
            seq.append(v); nxt = [(w, fi) for w, fi in graph[v] if w != prev]; prev = v
            if nxt: eids.append(nxt[0][1]); v = nxt[0][0]
            else: v = None
        if set(seq) != comp or len(eids) != len(seq) - 1: raise NotApplicable('invalid path witness')
        use = [i for i, v in enumerate(seq) if v in needS]; cut = min(use) if use else len(seq) - 1
        removedS.update(seq[:cut]); b = seq[cut]; rho = F(1); pid = len(path_edges); path_edges[pid] = eids[:cut]            # edge i joins seq[i] and seq[i + 1]; node seq[i] (i < cut) reaches the boundary through edges i .. cut - 1
        for i in range(cut - 1, -1, -1):
            if (i & 255) == 255: poll('inside the prefix witness')
            fi = eids[i]; r = chan[fi][2]; rho *= r; _bits_ok(rho, 'transport product'); edge_rho[fi] = r; node_pos[seq[i]] = (pid, i, cut); transport[seq[i]] = (b, rho); rho_at[pid, i] = rho
        cut_of[pid] = cut
        paths.append(dict(status='uniform_rooted', length=len(seq), cut=cut, needed=len(use)))
    removedA = alleles - retainedA
    if not removedA and not removedS: raise NotApplicable('nothing to erase (every allele / selector is needed)')
    # ---- 6. certified erasure: every source factor accounted once; build the reduced model
    retained_vars = [v for v in range(n) if v not in removedA and v not in removedS]; mapping = {v: i for i, v in enumerate(retained_vars)}; kept = []; scalar = F(1); erased = Counter(); seen_prior = set()
    for fi, f in enumerate(facs):
        if (fi & 63) == 63: poll('inside the erasure accounting')
        sc = set(f['scope'])
        if sc & removedA:
            if fi in mux_fid and mux_fid[fi] in removedA: erased['multiplexer'] += 1; continue
            if fi in founder_unary and len(sc) == 1 and next(iter(sc)) in removedA: erased['founder_unary'] += 1; continue   # its mass enters the scalar below (once per founder)
            raise NotApplicable('factor %d touches an erased allele but is neither its multiplexer nor a founder weight' % fi)
        if sc & removedS:
            if fi in chan and (chan[fi][0] in removedS or chan[fi][1] in removedS): erased['channel'] += 1; continue
            if len(sc) == 1 and next(iter(sc)) in removedS and fi in uniform[next(iter(sc))]: erased['uniform_prior'] += 1; continue
            raise NotApplicable('factor %d touches an erased selector but is neither a channel nor its uniform prior' % fi)
        kept.append(f)
    if set(ev) & (removedA | removedS): raise NotApplicable('evidence on an erased variable')
    for v in removedA:
        if v in mass: scalar *= mass[v]; _bits_ok(scalar, 'erasure scalar')
    newf = [dict(scope=tuple(mapping[v] for v in f['scope']), values=f['values']) for f in kept]
    B.charge(sum(len(f['values']) * 8 + 80 for f in newf), 'reduced model')
    for b in sorted({t[0] for t in transport.values()}): newf.append(dict(scope=(mapping[b],), values=[F(1, 2), F(1, 2)]))
    newf.append(dict(scope=(), values=[scalar]))                                                       # the erasure scalar: cancelled by lower(), restored once in the Z enclosure
    red = dict(cards=[cards[v] for v in retained_vars], factors=newf, evidence={mapping[v]: a for v, a in ev.items()})
    # ---- 7. sparse affine Walsh responses of every allele (retained alleles are indicators), transported to the boundaries
    coeff = {}; live = 0
    for v in order:
        poll('inside the response recursion')
        if v in retainedA: B.charge(cards[v] * _term_cost(0), 'retained indicator terms'); live += cards[v]; coeff[v] = [{(v, a, ()): F(1)} for a in range(cards[v])]
        elif v in founders: B.charge(cards[v] * _term_cost(0), 'founder prior terms'); live += cards[v]; coeff[v] = [({(-1, -1, ()): x} if x else {}) for x in priors[v]]
        else:
            pa, pb, s, fi = defs[v]; q = []; merged = 0
            for fa, fb in zip(coeff[pa], coeff[pb]):
                bound = 2 * (len(fa) + len(fb)); kmax = max((len(k_[2]) for k_ in fa), default=0); kmax = max(kmax, max((len(k_[2]) for k_ in fb), default=0)) + 1     # the merge creates at most two terms per input term, subsets at most one longer: ADMIT the temporary + stored result before building
                if live + bound > max_live_terms: raise ResourceRefused('live sparse response terms would reach %d > %d' % (live + bound, max_live_terms))
                B.charge(2 * bound * _term_cost(kmax), 'response merge temporary + stored terms (keys incl.)'); d = defaultdict(F)
                for sign, poly in ((1, fa), (-1, fb)):
                    for (r, t, Uset), c in poly.items():
                        merged += 1
                        if (merged & 1023) == 0: poll('inside the sparse merge')
                        d[r, t, Uset] += c / 2; d[r, t, tuple(sorted(set(Uset) ^ {s}))] += sign * c / 2
                qq = {k: c for k, c in d.items() if c}; q.append(qq); live += len(qq)
            coeff[v] = q
    decoder = {}; needed = set(); maxnorm = F(0); moved = 0
    for v in sorted(removedA):
        poll('inside the transport'); pp = []; nterms = sum(len(poly) for poly in coeff[v]); kmax = max((len(k_[2]) for poly in coeff[v] for k_ in poly), default=0)
        B.charge(nterms * _term_cost(kmax) + nterms * 160, 'decoder terms (transported polynomials, keys incl.) + the transport temporaries (boundary / parity maps per term)')                 # the transported polynomial has at most as many terms as its source: admitted before it is built
        for poly in coeff[v]:
            out = defaultdict(F)
            for (r, a, Uset), c in poly.items():
                moved += 1
                if (moved & 1023) == 0: poll('inside the transport')
                bset = set(); parity = defaultdict(int)                                                  # edge parity by (path id, index) ranges: node at position i covers edges i .. cut - 1 of its path
                for s_ in Uset:
                    if s_ in transport:
                        bset.symmetric_difference_update([transport[s_][0]]); pid, i, cut = node_pos[s_]; parity[pid, i] += 1; parity[pid, cut] -= 1
                    else: bset.symmetric_difference_update([s_])
                scale = F(1)
                for pid in {k[0] for k in parity}:                                                        # prefix-sum of the +-1 markers along the path gives each edge's traversal count
                    cnt = 0; marks = sorted(k[1] for k in parity if k[0] == pid)
                    for j in range(len(marks)):
                        cnt += parity[pid, marks[j]]; nxt = marks[j + 1] if j + 1 < len(marks) else marks[j]
                        if cnt % 2:
                            if nxt == cut_of[pid] and (pid, marks[j]) in rho_at: scale *= rho_at[pid, marks[j]]            # the run reaches the boundary: its product is the node's precomputed transport rho (exact, no recomputation)
                            else:
                                for e in path_edges[pid][marks[j]:nxt]: scale *= edge_rho[e]
                _bits_ok(scale, 'transport product'); out[r, a, tuple(sorted(bset))] += c * scale
            qq = {k: c for k, c in out.items() if c}
            for k, c in qq.items(): _bits_ok(c, 'response coefficient')
            needed.update(k for k in qq if not (k[0] < 0 and not k[2])); maxnorm = max(maxnorm, sum(abs(c) for k, c in qq.items() if k[0] >= 0 or k[2])); pp.append(qq)
        decoder[v] = pp
    # ---- 8. Boolean query auxiliaries (parity / mixed), appended as normalized deterministic sources
    aug = dict(cards=list(red['cards']), factors=list(red['factors']), evidence=dict(red['evidence'])); qvar = {}; entries = 0
    for key in sorted(needed, key=lambda k: (k[0], k[1], k[2])):
        r, a, Uset = key
        if r < 0 and len(Uset) <= 1: continue                                                           # a single boundary character is the retained selector's own marginal
        if not Uset: continue                                                                             # a retained marginal
        poll('inside the query construction'); sc = tuple(([mapping[r]] if r >= 0 else []) + [mapping[s] for s in Uset])
        if len(sc) != len(set(sc)): raise NotApplicable('query axes overlap')
        ne = 2 * math.prod(aug['cards'][x] for x in sc); entries += ne
        if entries > max_query_entries: raise ResourceRefused('appended query entries %d > %d' % (entries, max_query_entries))
        B.charge(ne * ENTRY_BYTES, 'query table'); y = len(aug['cards']); aug['cards'].append(2); vals = []
        off = 1 if r >= 0 else 0
        for ei, xs in enumerate(iproduct(*(range(aug['cards'][x]) for x in sc + (y,)))):
            if (ei & 1023) == 1023: poll('inside the query table generation')
            odd = sum(xs[off:-1]) % 2; pred = odd and (r < 0 or xs[0] == a); vals.append(F(int(xs[-1] == int(bool(pred)))))
        aug['factors'].append(dict(scope=sc + (y,), values=vals)); qvar[key] = y
    # ---- 9. deterministic weighted-min-product order on the PHYSICAL augmented graph + exact volume certificate
    try: pf, pscalar, pcancel = LC._restrict(aug, dl)
    except LC.RecognitionRefused as e: raise RecognitionRefused('construction allowance exhausted inside the physical restriction (%s)' % str(e)[:80])
    def physical_graph(label):
        # A k-axis source creates k(k-1) directed adjacency entries, even when
        # every axis has cardinality one. Admit that clique before materialising it.
        poll('before the physical graph construction (%s)' % label)
        B.charge(len(aug['cards']) * 384, 'physical adjacency vertices + dictionary (%s)' % label)
        graph_ = {v: set() for v in range(len(aug['cards'])) if v not in aug['evidence']}
        for k_, (sc, _) in enumerate(pf):
            if (k_ & 63) == 0: poll('inside the physical graph construction (%s)' % label)
            degree = len(sc)
            B.charge(GRAPH_ENTRY_BYTES * degree * (degree - 1) + 2 * (256 + GRAPH_ENTRY_BYTES * degree), 'physical source clique + temporary sets (%s)' % label)
            s_ = set(sc)
            for j_, v in enumerate(sc):
                if (j_ & 63) == 0: poll('inside the physical source clique (%s)' % label)
                graph_[v] |= s_ - {v}
        poll('after the physical graph construction (%s)' % label)
        return graph_
    def fill_graph(graph_, v, label):
        # Keep the original set expression/order. Its union and difference can
        # coexist with the old neighbor set; charge both before constructing them.
        nb_ = graph_[v]
        for j_, w in enumerate(nb_):
            if (j_ & 63) == 0: poll('inside the physical fill (%s)' % label)
            upper = len(graph_[w]) + len(nb_)
            B.charge(2 * (256 + GRAPH_ENTRY_BYTES * upper), 'physical fill temporary + replacement (%s)' % label)
            graph_[w] = (graph_[w] | nb_) - {w, v}
        del graph_[v]
    adj = physical_graph('order')
    import random as _r
    rng = _r.Random(0); ties = {v: rng.random() for v in adj}; porder = []; acards = aug['cards']
    while adj:
        best = None
        for k, (v, ns) in enumerate(adj.items()):
            if (k & 63) == 63: poll('inside the order scoring')
            out = math.prod(acards[w] for w in ns); key = (out * acards[v], out, len(ns), ties[v])
            if best is None or key < best[0]: best = (key, v)
        v = best[1]; nb = adj[v]
        fill_graph(adj, v, 'order'); porder.append(v)
        if (len(porder) & 63) == 63: poll('inside the order scoring (eliminations)')
    adj = physical_graph('certificate')
    if sorted(porder) != sorted(adj): raise NotApplicable('physical order does not cover the unobserved variables (constructor defect, refused)')
    mp = mo = sp = so = 0; live = [set(sc) for sc, _ in pf]; fpb_max = 0; fpb_sum = 0; work = 0
    for k, v in enumerate(porder):
        if (k & 63) == 63: poll('inside the physical certificate')
        nb = adj[v]; p = acards[v] * math.prod(acards[w] for w in nb); mp = max(mp, p); mo = max(mo, p // acards[v]); sp += p; so += p // acards[v]
        fill_graph(adj, v, 'certificate')
        bucket = [sc for sc in live if v in sc]; nf = len(bucket); fpb_max = max(fpb_max, nf); fpb_sum += nf; work += (nf + 1) * p          # relations (sources + messages) joined in this bucket: equal row counts can have different arithmetic cost
        live = [sc for sc in live if v not in sc] + [set().union(*bucket) - {v}] if bucket else live
    sp += len(aug['evidence']); so += len(aug['evidence'])
    vol = dict(max_product_entries=mp, max_output_entries=mo, sum_product_entries=sp, sum_output_entries=so, source_entries=sum(len(d) for _, d in pf), retained_sources=len(pf), observed_variables=len(aug['evidence']), native_variables=len(acards), native_coordinates=sum(acards), bucket_factors_max=fpb_max, bucket_factors_mean=(fpb_sum / max(1, len(porder))), weighted_bucket_work=work, graph='physical: every retained evidence-restricted source scope incl. the query auxiliaries, full native bucket order')
    poll('before the plan is returned')
    P = Plan(); P.aug = aug; P.order = porder; P.cancelled_scalar = pscalar; P.cancelled_count = pcancel; P.mapping = mapping; P.cards_orig = list(cards); P.ev_orig = dict(ev); P.decoder = decoder; P.selector_transport = transport; P.qvar = qvar
    P.retained = retained_vars; P.removed_alleles = sorted(removedA); P.removed_selectors = sorted(removedS); P.scalar = scalar; P.volume = vol; P.bytes_charged = B.charged
    P.structure = dict(multiplexers=len(defs), founders=len(founders), selectors=len(selectors), channels=len(chan), residual_factors=len(resid), uniform_selector_priors=sum(map(len, uniform.values())), paths=dict(Counter(p['status'] for p in paths)), cut_paths=sum(1 for p in paths if p['status'] == 'uniform_rooted' and p['cut'] > 0), retained_original_variables=len(retained_vars), retained_alleles=len(retainedA), removed_alleles=len(removedA), removed_selectors=len(removedS), removed_founders=sum(1 for v in removedA if v in mass), erased_factors=dict(erased), query_auxiliaries=len(qvar), parity_queries=sum(1 for k in qvar if k[0] < 0), mixed_queries=sum(1 for k in qvar if k[0] >= 0), max_query_degree=max((len(k[2]) for k in qvar), default=0), max_response_l1=str(maxnorm), scalar_bits=(scalar.numerator.bit_length(), scalar.denominator.bit_length()), predicate_checks=counter[0], construction_bytes_charged=B.charged)
    P.recognition_s = tnow() - t0; P.binding = binding; P.forecast = None
    return P


def forecast(plan, remaining_s, n_original_coordinates):
    """the layered route's physical live-state formula on the augmented graph + the decode state (response terms, rows)"""
    from types import SimpleNamespace
    fc = LC.forecast(SimpleNamespace(volume=plan.volume, cards=plan.aug['cards']), remaining_s)
    terms = sum(len(p) for pp in plan.decoder.values() for p in pp); fc['forecast_bytes'] += terms * TERM_BYTES + ROW_BYTES * n_original_coordinates; fc['decode_terms'] = terms
    return fc


def _scale(lo, hi, c): return (c * lo, c * hi) if c >= 0 else (c * hi, c * lo)


def decode(plan, R, eps, deadline=math.inf):
    """every ORIGINAL unobserved coordinate from the executor's enclosures: retained -> its row; removed selector -> (1 - rho E chi_b) / 2; removed allele -> the sparse affine response;
    exact signed interval arithmetic, [0, 1] intersection; returns {orig var: [(lo, hi, point)]} with points chosen in the epsilon-safe J intervals when feasible (else midpoints)"""
    def poll(where):
        if tnow() >= deadline: raise DeadlineRefused('deadline %s (nothing published)' % where)
    mp = plan.mapping; qv = plan.qvar; cards = plan.cards_orig
    def row(v, a): lo, hi = R.intervals[v][a]; return lo, hi, R.points[v][a]
    cache = {}
    def atom(key):
        if key in cache: return cache[key]
        r, a, Uset = key
        if r < 0 and not Uset: val = (F(1), F(1), F(1))
        elif r < 0:
            var = mp[Uset[0]] if len(Uset) == 1 else qv[key]; lo, hi, p = row(var, 1); val = (1 - 2 * hi, 1 - 2 * lo, 1 - 2 * p)
        else:
            lo, hi, p = row(mp[r], a)
            if not Uset: val = (lo, hi, p)
            else: ql, qh, qp = row(qv[key], 1); val = (lo - 2 * qh, hi - 2 * ql, p - 2 * qp)
        cache[key] = val; return val
    answers = {}
    for v, w in mp.items():
        if v in plan.ev_orig: continue
        answers[v] = [row(w, a) for a in range(cards[v])]
    for k, (s, (b, rho)) in enumerate(plan.selector_transport.items()):
        if (k & 255) == 255: poll('inside the selector decode')
        lo, hi, p = atom((-1, -1, (b,))); sl, sh = _scale(lo, hi, rho); one = ((1 - sh) / 2, (1 - sl) / 2, (1 - rho * p) / 2); answers[s] = [(1 - one[1], 1 - one[0], 1 - one[2]), one]
    for k, (v, pp) in enumerate(plan.decoder.items()):
        if (k & 63) == 63: poll('inside the allele decode')
        rs = []
        for poly in pp:
            lo = hi = p = F(0)
            for ti, (key, c) in enumerate(poly.items()):
                if (ti & 255) == 255: poll('inside the allele decode (terms)')
                l, h, pt = atom(key); a_, b_ = _scale(l, h, c); lo += a_; hi += b_; p += c * pt
            lo = max(F(0), lo); hi = min(F(1), hi); rs.append((lo, hi, min(hi, max(lo, p))))
        answers[v] = rs
    expected = [v for v in range(len(cards)) if v not in plan.ev_orig]
    if sorted(answers) != expected or any(len(answers[v]) != cards[v] for v in answers): raise AssertionError('original query coverage mismatch')
    policies = Counter(); Q = 1 << 52
    def compact(lo, hi):
        L = max(F(0), F(math.floor(lo * Q), Q)); H = min(F(1), F(-((-hi * Q).numerator // (-hi * Q).denominator), Q)); return L, H
    for k, v in enumerate(expected):
        if (k & 63) == 63: poll('inside the point normalisation')
        rs = [(*compact(lo, hi), p) for lo, hi, p in answers[v]]
        if any(not (0 <= lo <= hi <= 1) or hi - lo > 2 * eps for lo, hi, _ in rs): raise AssertionError('decoded interval of variable %d violates the contract' % v)
        if not (sum(lo for lo, _, _ in rs) <= 1 <= sum(hi for _, hi, _ in rs)): raise AssertionError('decoded interval box of variable %d excludes the simplex' % v)
        J = [(max(lo, hi - eps), min(hi, lo + eps)) for lo, hi, _ in rs]
        if all(lo <= hi for lo, hi in J) and sum(lo for lo, _ in J) <= 1 <= sum(hi for _, hi in J):
            pp = [min(hi, max(lo, p)) for (lo, hi), (_, _, p) in zip(J, rs)]; diff = 1 - sum(pp)
            for i, (lo, hi) in enumerate(J):
                take = min(diff, hi - pp[i]) if diff > 0 else -min(-diff, pp[i] - lo); pp[i] += take; diff -= take
            if diff != 0: raise AssertionError('simplex projection failed')
            answers[v] = [(lo, hi, p) for (lo, hi, _), p in zip(rs, pp)]; policies['normalized_J'] += 1
        else: answers[v] = [(lo, hi, (lo + hi) / 2) for lo, hi, _ in rs]; policies['interval_midpoints'] += 1
    poll('before the decoded answers are returned')
    return answers, dict(policies)
