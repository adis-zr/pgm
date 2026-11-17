"""PROTECTED COMPLETE EXACT REFERENCE (manuscript §7 step 1, §8 Theorem 8.1): a streaming exact rational enumerator over the ORIGINAL task (original tables, original
queries, evidence) in fixed mixed-radix order, resumable in charged quanta (a generator that yields after every `quantum` evaluations). Its state is the current
assignment index + exact accumulators; memory is O(input + accumulators). It never consults the compiler. Completion => exact answers (or ZERO_EVIDENCE / per-query
UNDEFINED) with a certificate the checker re-derives by the same enumeration (or by the independent oracle)."""
from fractions import Fraction as F
from math import prod, lcm


class Reference:
    def __init__(self, model, queries, work):
        self.model = model; self.queries = queries; self.work = work; cards = model['cards']; ev = model.get('evidence', {})
        self.free = [v for v in range(len(cards)) if v not in ev]; self.total = prod(cards[v] for v in self.free); self.idx = 0
        self.x = [ev.get(v, 0) for v in range(len(cards))]; self.done = False; self.radix = [cards[v] for v in self.free]
        # integer tables: factor a -> ivals (values * den_a); scale_den = prod den_a; query j -> (tables * qden_j)
        self.fden = [lcm(*[F(v).denominator for v in f['values']]) if f['values'] else 1 for f in model['factors']]
        self.ftab = [[int(F(v) * d) for v in f['values']] for f, d in zip(model['factors'], self.fden)]; self.fscope = [tuple(f['scope']) for f in model['factors']]
        self.scale_den = prod(self.fden) if self.fden else 1
        self.qden = []; self.qtab = []
        for q in queries:
            if q.kind == 'expectation': d = lcm(*[F(v).denominator for v in q.f.values]); self.qden.append(d); self.qtab.append(([int(F(v) * d) for v in q.f.values], None))
            else: d = lcm(*[F(v).denominator for v in q.h.values + q.g.values]); self.qden.append(d); self.qtab.append(([int(F(v) * d) for v in q.h.values], [int(F(v) * d) for v in q.g.values]))
        self.Zi = 0; self.numi = [0] * len(queries); self.deni = [0] * len(queries); self.qreads = sum(1 if q.kind == 'expectation' else 2 for q in queries)
    def _set(self, k):
        for v, c in zip(reversed(self.free), reversed(self.radix)): self.x[v] = k % c; k //= c
    def step(self, quantum):
        """evaluate up to `quantum` assignments; returns the number evaluated"""
        if self.done: return 0
        cards = self.model['cards']; n = 0; end = min(self.total, self.idx + quantum); x = self.x; ftab = self.ftab; fscope = self.fscope; qs = self.queries; qtab = self.qtab; ent = 0
        while self.idx < end:
            self._set(self.idx); self.idx += 1; n += 1; w = 1
            for tab, sc in zip(ftab, fscope):
                i = 0
                for v in sc: i = i * cards[v] + x[v]
                w *= tab[i]; ent += 1
                if not w: break
            self.work.evals += 1
            if not w: continue
            ent += self.qreads                      # one lookup per expectation query, two per ratio query (numerator AND denominator; seventh review, CQR-R6-04)
            self.Zi += w
            for j, q in enumerate(qs):
                ht, gt = qtab[j]
                if gt is None:
                    i = 0
                    for v in q.f.scope: i = i * cards[v] + x[v]
                    self.numi[j] += w * ht[i]
                else:
                    i = 0
                    for v in q.h.scope: i = i * cards[v] + x[v]
                    self.numi[j] += w * ht[i]; i = 0
                    for v in q.g.scope: i = i * cards[v] + x[v]
                    self.deni[j] += w * gt[i]
        self.work.entries += ent                       # every table lookup is one unit (the SAME currency as the optional half's scans)
        if self.idx >= self.total: self.done = True
        return n
    @property
    def Z(self): return F(self.Zi, self.scale_den)
    @property
    def num(self): return [F(self.numi[j], self.qden[j] * self.scale_den) for j in range(len(self.queries))]
    @property
    def den(self): return [F(self.deni[j], self.qden[j] * self.scale_den) for j in range(len(self.queries))]
    def progress(self): return self.idx / self.total if self.total else 1.0
    def result(self):
        assert self.done
        if self.Zi == 0: return dict(kind='ZERO_EVIDENCE', Z='0', assignments=self.total)
        Z = self.Z; num = self.num; den = self.den; ans = []
        for j, q in enumerate(self.queries):
            if q.kind == 'expectation': ans.append(num[j] / Z)
            else: ans.append(num[j] / den[j] if den[j] else 'UNDEFINED')
        return dict(kind='EXACT', Z=str(Z), answers=[str(a) for a in ans], numerators=[str(x) for x in num], denominators=[str(den[j] if self.queries[j].kind == 'ratio' else Z) for j in range(len(self.queries))], assignments=self.total)
