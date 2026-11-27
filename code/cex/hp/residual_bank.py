"""DGP7 RESIDUAL_JOINT, part 1: the residual bank (theory sections 2-3; brief sections 2-3). The engine's retained state is the envelope identity W <= envelope_B q prod_j rho_j, 0 <= rho_j <= 1, with IMMUTABLE compact atoms (scope,
upward values, checked provenance) extracted during the EXISTING checked seed pass: at every MAX group of the seed compiler (mode 'seed'; group 0 is the SUM group that defines the conditional), with the live inputs A_g, the normalized
upward product P_g and the checked upward message M_g, rho_g = P_g / M_g <= 1 cellwise (exact P_g <= M_g by the checked MAX dominance; the upward division is clipped to one only because of it; M_g = 0 -> rho_g = 1 and the checked
reduction implies P_g = 0 there). The INDEPENDENT slack check runs while the inputs and message are live: for every cell, the EXACT product of the actual inputs A_g <= M_g rho_hat (exact big-integer comparison). Nothing becomes an atom
before that check. Retention rule (frozen; brief section 3): unit atoms ignored; score = -ln(mean_uniform(rho)) / retained_bytes (bounded floating logs; advisory, never a mass estimate); ties by (stage, group); <= 64 atoms, <= 131,072
entries, inside the 64 MiB branch cap and the shared constructor account; a candidate's TEMPORARY is admitted before materialization; a full bank keeps the higher-scored atom and records the loss; the extra work is limited to 15 % of the
one absolute optional allowance (at the limit the ordinary seed continues without capture); optional atoms are EVICTED before their bytes would make the ordinary seed's next allocation fail (the sink's make_room hook runs before every
stage charge of the seed compiler). The bank records coverage, scopes, entries, dropped / evicted atoms, checking cost and the exact seed cap. A deserialized dictionary is never a trusted atom: `verified` is set only by the check in this
module (extraction) or by check_residual's transactional kernel (replacement atoms). Content hashes identify atoms; they never establish an inequality."""
import math, hashlib, itertools, time
from fractions import Fraction as F
import numpy as np
import coarse_envelope as CE
import residual_max_envelope as RM
from residual_max_envelope import ZERO, norm_up, from_fraction_up, to_fraction, mul_exact, ge_exact, lead, log2_up, MBITS
from joint_proposal import vol_of, D, D_BITS, ENTRY_BYTES
ARITH_VERSION = 'compact-128-upward / DGP7'
BANK_MAX_ATOMS = 64; BANK_MAX_ENTRIES = 131072; BRANCH_CAP_BYTES = 64 << 20; RETENTION_SHARE = 0.15; ATOM_META_BYTES = 512


class RefusedResidual(Exception):
    def __init__(self, kind, reason): super().__init__(kind, reason); self.kind = kind; self.reason = reason


def div_up(P, M):
    """upward compact P / M for normalized nonnegative pairs with M > 0: q = ceil(m_P 2^MBITS / m_M) at exponent e_P - e_M - MBITS, normalized upward (mantissas stay <= 2 MBITS + 1 bits; nothing proportional to an exponent gap)"""
    if P[1] == 0: return ZERO
    eP, mP = P; eM, mM = M; num = mP << MBITS; q = num // mM
    if q * mM != num: q += 1
    return norm_up(eP - eM - MBITS, q)


ONE = (0, 1)
def one_compact(): return norm_up(0, 1)


def content_sha(arr):
    """sha256 of a compact object array's content (exponents and mantissas) -- an IDENTITY, not an inequality"""
    h = hashlib.sha256(); h.update(repr(arr.shape).encode())
    for x in arr.reshape(-1): h.update(('%d:%x;' % (x[0], x[1])).encode())
    return h.hexdigest()


class Atom:
    """an immutable residual factor rho over `axes` (sorted variable ids) with compact upward values in [0, 1]; `provenance` binds the extraction (stage, group, input ids + content hashes, message id + hash, aggregation, arithmetic version,
    cells checked) or the replacement transaction; `verified` is set ONLY by the independent check that established the inequality"""
    __slots__ = ('aid', 'axes', 'arr', 'bytes', 'provenance', 'score', 'mean_log2', 'consumed', 'verified', 'version_born', 'sha256')
    def __init__(self, aid, axes, arr, provenance, score, mean_log2, version_born):
        self.aid = int(aid); self.axes = tuple(axes); self.arr = arr; self.arr.setflags(write=False); self.bytes = ENTRY_BYTES * int(arr.size) + ATOM_META_BYTES; self.provenance = dict(provenance); self.score = float(score); self.mean_log2 = float(mean_log2); self.consumed = False; self.verified = False; self.version_born = int(version_born); self.sha256 = content_sha(arr)
    def entries(self): return int(self.arr.size) if self.arr is not None else 0
    def record(self): return dict(aid=self.aid, axes=list(self.axes), entries=self.entries(), array_released=(self.arr is None), bytes=self.bytes, score=self.score, mean_log2=self.mean_log2, consumed=self.consumed, verified=self.verified, version_born=self.version_born, sha256=self.sha256, provenance={k: v for k, v in self.provenance.items() if k not in ('input_shas',)})


def rho_of_group(P, T_msg, u, raxes, cards, clock, tag=''):
    """the upward residual rho = P / M over the union axes u (M broadcast from the message over raxes); M = 0 -> 1 (P must be zero there: Defect otherwise -- the checked MAX dominance guarantees it); clipped to one AFTER the exact
    P <= M (also guaranteed by dominance; re-asserted exactly here)"""
    shape = [cards[a] for a in u]; rho = np.empty(shape, dtype=object); mi = [u.index(a) for a in raxes]; unit = True; lsum = 0.0; n = 0
    for k_, idx in enumerate(itertools.product(*[range(s) for s in shape])):
        M = T_msg.arr[tuple(idx[p] for p in mi)] if raxes else T_msg.arr.reshape(-1)[0]; Pz = P[idx]
        if M[1] == 0:
            if Pz[1] != 0: raise CE.Defect('residual extraction: zero message with a positive product at %s' % (idx,))
            rho[idx] = ONE; lsum += 0.0
        else:
            if not ge_exact(M, Pz): raise CE.Defect('residual extraction: P > M at %s (MAX dominance violated)' % (idx,))
            r = div_up(Pz, M)
            if ge_exact(r, ONE): r = ONE                                                                        # the exact ratio is <= 1 (P <= M): the upward rounding may exceed one; clip
            else: unit = False
            rho[idx] = r; lsum += (log2_up(r) if r[1] else -1024.0)
        n += 1
        if (k_ & 255) == 255: clock.poll('residual rho %s' % tag)
    return rho, unit, (lsum / max(1, n))


def check_slack_cells(mem, T_msg, rho, u, raxes, cards, clock, tag=''):
    """the INDEPENDENT slack check while the inputs and message are live: the EXACT product of the actual inputs at every cell of u <= M x rho_hat (exact big-integer comparison); returns the cell count"""
    sizes = [cards[a] for a in u]; ipos = [[u.index(a) for a in T.axes] for T in mem]; mi = [u.index(a) for a in raxes]; cells = 0
    for k_, asg in enumerate(itertools.product(*[range(s) for s in sizes])):
        prod = (0, 1)
        for T, pp in zip(mem, ipos):
            x = T.arr[tuple(asg[p] for p in pp)]
            if x[1] == 0: prod = ZERO; break
            prod = (prod[0] + x[0], prod[1] * x[1])
        r_ = rho[asg]
        if (not isinstance(r_, tuple)) or len(r_) != 2 or r_[1] < 0 or (r_[1] and not ge_exact(ONE, r_)): raise CE.Defect('residual slack check: rho outside the exact closed interval [0, 1] at %s (DGP9 repair of the original DGP7 finding F2 at the standalone checker)' % (asg,))
        M = T_msg.arr[tuple(asg[p] for p in mi)] if raxes else T_msg.arr.reshape(-1)[0]; bound = mul_exact(M, r_) if (M[1] and r_[1]) else ZERO
        if not ge_exact(bound, prod): raise CE.Defect('residual slack check: inputs product exceeds M rho at %s' % (asg,))
        cells += 1
        if (k_ & 255) == 255: clock.poll('residual slack check %s' % tag)
    return cells


class ResidualState:
    """the retained envelope state of ONE stream: W <= envelope_B q prod rho (envelope_B in W_0 units); consumed_B = the cap the PAC epoch actually uses (may be tightened by a separate valid scalar; never replaces envelope_B);
    initial_seed_cap = the frozen ceiling anchor; immutable atoms; the ownership ledger (bytes charged to the shared constructor account on the stream's behalf)"""
    def __init__(self, model_identity, seed_proof_identity, law, envelope_B, consumed_B, initial_seed_cap, budget):
        self.model_identity = model_identity; self.seed_proof_identity = seed_proof_identity; self.version = 0; self.law = law; self.law_identity = (law.sha256 if law is not None else None); self.envelope_B = envelope_B; self.consumed_B = consumed_B; self.initial_seed_cap = initial_seed_cap
        self.atoms = {}; self.next_aid = 0; self.budget = budget; self.owned = 0; self.ledger = []; self.dropped = []; self.evicted = []; self.transactions = []; self.check_seconds = 0.0; self.check_cells = 0
    def bind_seed(self, prop, seed_proof_identity):
        """after the checked seed pass: the law the atoms were extracted against, its cap as envelope_B = consumed_B = initial_seed_cap (W <= B_seed q_seed prod rho is the seed identity)"""
        self.law = prop; self.law_identity = prop.sha256; self.seed_proof_identity = seed_proof_identity; self.envelope_B = prop.B; self.consumed_B = prop.B; self.initial_seed_cap = prop.B
        for a in self.atoms.values(): a.provenance['seed_law_identity'] = prop.sha256
    def apply_transaction(self, txn, newp, new_atom_axes, new_atom_arr, new_atom_bytes, provenance, score, mean_log2, B_new):
        """the bounded swap of ONE checked transaction (every variable-size object already built and admitted): consume the selected atoms exactly once, install the replacement atom, advance the version, rebind the law and the
        envelope constant (consumed_B follows it); returns an undo record for a failed epoch commit"""
        undo = dict(version=self.version, law=self.law, law_identity=self.law_identity, envelope_B=self.envelope_B, consumed_B=self.consumed_B, consumed=list(txn['atoms']), new_aid=None)
        self.consume(txn['atoms'], txn['id']); a = self.add_atom(new_atom_axes, new_atom_arr, provenance, score, mean_log2, new_atom_bytes); undo['new_aid'] = a.aid
        self.version += 1; self.law = newp; self.law_identity = newp.sha256; self.envelope_B = B_new; self.consumed_B = B_new; a.version_born = self.version; self.transactions.append(dict(txn, new_atom=a.aid, version_after=self.version)); return undo
    def revert_transaction(self, undo):
        """a failed epoch commit after the swap: the bank / law / envelope return to the pre-transaction state (the atom bytes stay charged by the caller's workspace release)"""
        if undo['new_aid'] is not None and undo['new_aid'] in self.atoms:
            a = self.atoms.pop(undo['new_aid']); a.bytes = 0
        for aid in undo['consumed']:
            self.atoms[aid].consumed = False; self.atoms[aid].provenance.pop('consumed_by', None)
        self.version = undo['version']; self.law = undo['law']; self.law_identity = undo['law_identity']; self.envelope_B = undo['envelope_B']; self.consumed_B = undo['consumed_B']
        if self.transactions: self.transactions[-1] = dict(self.transactions[-1], reverted=True)
    def live_atoms(self): return [a for a in self.atoms.values() if not a.consumed]
    def entries(self): return sum(a.entries() for a in self.live_atoms())
    def bytes_live(self): return sum(a.bytes for a in self.live_atoms())
    def _charge(self, n, what):
        self.budget.charge(n, what); self.owned += n; self.ledger.append(('charge', n, what)); return n
    def _release(self, n, what):
        self.budget.release(n); self.owned -= n; self.ledger.append(('release', n, what))
    def add_atom(self, axes, arr, provenance, score, mean_log2, charged_bytes):
        """install an ALREADY-CHECKED atom whose bytes were admitted by the caller (`charged_bytes` already in the ledger)"""
        a = Atom(self.next_aid, axes, arr, provenance, score, mean_log2, self.version); a.verified = True; a.bytes = charged_bytes; self.next_aid += 1; self.atoms[a.aid] = a; return a
    def drop_atom(self, aid, why):
        a = self.atoms.pop(aid); self._release(a.bytes, 'residual atom %d dropped (%s)' % (aid, why)); self.evicted.append(dict(aid=aid, axes=list(a.axes), entries=a.entries(), score=a.score, why=why)); return a
    def consume(self, aids, txn):
        # DGP9 repair (original DGP7 finding F1): the COMPLETE consumption inventory is preflighted (repeated ids, unknown ids, already-consumed atoms) BEFORE any atom is mutated
        aids = list(aids)
        if len(set(aids)) != len(aids): raise CE.Defect('residual consumption inventory repeats an atom id: %s' % aids)
        for aid in aids:
            if aid not in self.atoms: raise CE.Defect('residual atom %s not in the bank' % aid)
            if self.atoms[aid].consumed: raise CE.Defect('residual atom %d consumed twice' % aid)
        for aid in aids:
            a = self.atoms[aid]
            if a.consumed: raise CE.Defect('residual atom %d consumed twice' % aid)
            a.consumed = True; a.provenance['consumed_by'] = txn
    def release_consumed(self, txn_id):
        """after a COMMITTED transaction: the consumed atoms' arrays are dropped (their records, scopes, hashes and provenance stay) and their bytes released -- never before the epoch commit succeeded (the revert needs them)"""
        freed = 0
        for a in self.atoms.values():
            if a.consumed and a.bytes and a.arr is not None:
                n = a.bytes; a.arr = None; a.bytes = 0; self._release(n, 'consumed atom %d released after %s' % (a.aid, txn_id)); freed += n
        return freed
    def release_all(self):
        for a in list(self.atoms.values()):
            if a.bytes and self.owned > 0: self._release(min(a.bytes, self.owned), 'residual bank close'); a.bytes = 0
        self.atoms.clear(); self.owned = max(0, self.owned)
    def record(self):
        live = self.live_atoms(); pr = lambda x: ((x[0], str(x[1])) if x is not None else None); l2 = lambda x: ((log2_up(x) if x[1] else -math.inf) if x is not None else None); return dict(version=self.version, law_identity=self.law_identity, envelope_B=pr(self.envelope_B), log2_envelope_B=l2(self.envelope_B), consumed_B=pr(self.consumed_B), log2_consumed_B=l2(self.consumed_B), log2_initial_seed_cap=l2(self.initial_seed_cap),
                                              atoms=len(self.atoms), live_atoms=len(live), entries=self.entries(), bytes=self.bytes_live(), owned_bytes=self.owned, scopes=[list(a.axes) for a in live][:64], scores=[round(a.score, 6) for a in live][:64], mean_log2=[round(a.mean_log2, 4) for a in live][:64], dropped=self.dropped[:64], evicted=self.evicted[:64], transactions=self.transactions, check_seconds=self.check_seconds, check_cells=self.check_cells, model_identity=self.model_identity, seed_proof_identity=self.seed_proof_identity)


class BankSink:
    """attached to the seed compiler (JointCompile(..., sink=...)): `prepare` forms the candidate atom of a MAX group BEFORE the stage check (admitted temporary; rho = upward P / M), the stage checker verifies M rho >= the exact
    input product in its own exact pass, `commit` installs it (or drops it with the checker's reason), `abort` releases it; `make_room` evicts before every ordinary seed charge. Time rules: retention work <= time_cap_s (<= 15 % of the
    allowance) and no new atom after `phase_share` of the seed phase has elapsed (the remaining phase belongs to the seed itself: the optional bank never turns a valid seed into a deadline)"""
    SCORE_SAMPLES = 256
    def __init__(self, state, clock, time_cap_s, max_atoms=BANK_MAX_ATOMS, max_entries=BANK_MAX_ENTRIES, branch_cap_bytes=BRANCH_CAP_BYTES, branch_owned_fn=None, phase=None, phase_share=0.6):
        self.state = state; self.clock = clock; self.time_cap_s = float(time_cap_s); self.spent = 0.0; self.max_atoms = max_atoms; self.max_entries = max_entries; self.branch_cap = branch_cap_bytes; self.branch_owned_fn = branch_owned_fn or (lambda: 0); self.offers = 0; self.unit_atoms = 0; self.time_limited = 0; self.phase_limited = 0; self.slack_rejected = 0; self.pending = []
        self.phase = phase; self.phase_share = float(phase_share)
    def make_room(self, needed_bytes):
        """evict the lowest-scored optional atoms until the ordinary allocation of `needed_bytes` fits the shared account (never let the optional bank turn a valid seed into a refusal)"""
        B = self.state.budget
        while B.live + needed_bytes > B.cap and self.state.atoms:
            worst = min(self.state.atoms.values(), key=lambda a: (a.score, -a.aid)); self.state.drop_atom(worst.aid, 'evicted: the ordinary seed allocation of %d B would have failed' % needed_bytes)
    def _advisory_mean(self, P, T_msg, u, raxes, cards, vol):
        """mean_uniform(rho) over <= SCORE_SAMPLES cells (deterministic stride; bounded floating logs of the LIVE values): advisory only"""
        shape = [cards[a] for a in u]; mi = [u.index(a) for a in raxes]; step = max(1, vol // self.SCORE_SAMPLES); acc = 0.0; n = 0; unit = True; Pf = P.reshape(-1); st = CE.strides(shape)
        for flat in range(0, vol, step):
            idx = []; r_ = flat
            for s_ in st: idx.append(r_ // s_); r_ %= s_
            M = T_msg.arr[tuple(idx[p] for p in mi)] if raxes else T_msg.arr.reshape(-1)[0]; Pz = Pf[flat]
            if M[1] == 0 or Pz[1] == 0: r = 1.0 if M[1] == 0 else 0.0
            else: r = min(1.0, 2.0 ** (log2_up(Pz) - log2_up(M)))
            if r < 1.0 - 2 ** -40: unit = False
            acc += r; n += 1
        return acc / max(1, n), unit, n
    def prepare(self, v, gi, mem, P, u, T_msg, raxes, cards):
        """-> pending dict (rho formed, temporary admitted) or None (skipped with its reason recorded)"""
        self.offers += 1; t0 = CE.tnow()
        try:
            if self.spent >= self.time_cap_s: self.time_limited += 1; return None
            if self.phase is not None and CE.tnow() > self.phase[0] + self.phase_share * (self.phase[1] - self.phase[0]): self.phase_limited += 1; return None
            vol = vol_of(u, cards); need = ENTRY_BYTES * vol + ATOM_META_BYTES
            mean, unit, nsmp = self._advisory_mean(P, T_msg, u, raxes, cards, vol)
            if unit or mean >= 1.0 - 2 ** -40: self.unit_atoms += 1; return None
            score = (-math.log(max(mean, 2 ** -1000))) / need
            # DGP9 repair (original DGP7 finding F5, extraction): eviction is REPEATED until the incoming atom really fits every profile constraint (atoms / entries / bytes / branch ownership), or the candidate is dropped when a
            # retained atom with a higher score would have to go (the DGP8 code evicted at most one atom and never rechecked the fit)
            def over():
                live_ = self.state.live_atoms(); return (len(live_) >= self.max_atoms) or (self.state.entries() + vol > self.max_entries) or (self.state.bytes_live() + need > self.branch_cap) or (self.branch_owned_fn() + need > self.branch_cap)
            evicted_here = 0
            while over():
                live = self.state.live_atoms(); worst = min(live, key=lambda a: (a.score, -a.aid)) if live else None
                if worst is None or worst.score >= score: self.state.dropped.append(dict(stage=v, group=gi, axes=list(u), entries=vol, score=score, evicted_before_drop=evicted_here, why='bank full (atoms %d / entries %d / bytes %d); lower score than every retained atom (or no atom left to evict)' % (len(live), self.state.entries(), self.state.bytes_live()))); return None
                self.state.drop_atom(worst.aid, 'replaced by a higher-scored atom (stage %d group %d)' % (v, gi)); evicted_here += 1
            if over(): raise CE.Defect('residual extraction: the bank limits still fail after eviction')
            try: self.state._charge(need, 'residual atom temporary (stage %d group %d, %d entries)' % (v, gi, vol))
            except CE.Refused as e: self.state.dropped.append(dict(stage=v, group=gi, axes=list(u), entries=vol, score=score, why='admission refused: %s' % str(getattr(e, 'reason', e))[:80])); return None
            try: rho, unit2, mean_log2 = rho_of_group(P, T_msg, u, raxes, cards, self.clock, 'stage %d group %d' % (v, gi))
            except BaseException: self.state._release(need, 'atom construction failed'); raise
            if unit2: self.state._release(need, 'unit atom'); self.unit_atoms += 1; return None
            return dict(v=v, gi=gi, u=tuple(u), raxes=tuple(raxes), vol=vol, need=need, rho=rho, score=score, mean_log2=mean_log2, score_samples=nsmp)
        finally:
            dt = CE.tnow() - t0; self.spent += dt; self.state.check_seconds += dt
    def abort(self, pre):
        self.state._release(pre['need'], 'atom aborted (stage check failed)')
    def commit(self, pre, receipt, mem, T_msg):
        t0 = CE.tnow()
        try:
            if not receipt.get('ok') or receipt.get('slack_ok') is not True:
                self.state._release(pre['need'], 'atom rejected by the stage checker'); self.slack_rejected += 1; self.state.dropped.append(dict(stage=pre['v'], group=pre['gi'], axes=list(pre['u']), entries=pre['vol'], score=pre['score'], why='stage checker: %s' % (receipt.get('slack_why') or receipt.get('why') or 'slack not verified'))); return None
            self.state.check_cells += receipt.get('slack_cells', 0)
            prov = dict(kind='seed_max_slack', stage=pre['v'], group=pre['gi'], input_ids=[t.tid for t in mem], input_origins=[str(t.origin) for t in mem], input_shas=[content_sha(t.arr) for t in mem], message_id=T_msg.tid, message_sha=content_sha(T_msg.arr), union_axes=list(pre['u']), message_axes=list(pre['raxes']), eliminated=pre['v'], agg='max', arithmetic=ARITH_VERSION, cells_checked=receipt.get('slack_cells', 0), inequality='M(x_{u \\ v}) rho(x_u) >= the exact product of the live inputs at every union cell (verified inside the stage checker\'s exact pass); rho = upward P / M clipped at one after P <= M')
            return self.state.add_atom(pre['u'], pre['rho'], prov, pre['score'], pre['mean_log2'], pre['need'])
        finally:
            dt = CE.tnow() - t0; self.spent += dt; self.state.check_seconds += dt
    def offer(self, v, gi, mem, P, u, T_msg, raxes, cards):
        """stand-alone form (controls / references): prepare + the independent slack check + commit"""
        pre = self.prepare(v, gi, mem, P, u, T_msg, raxes, cards)
        if pre is None: return None
        try: cells = check_slack_cells(mem, T_msg, pre['rho'], u, raxes, cards, self.clock, 'stage %d group %d' % (v, gi))
        except CE.Defect as e: self.abort(pre); self.slack_rejected += 1; self.state.dropped.append(dict(stage=v, group=gi, axes=list(u), entries=pre['vol'], score=pre['score'], why=str(e)[:120])); return None
        return self.commit(pre, dict(ok=True, slack_ok=True, slack_cells=cells), mem, T_msg)
    def record(self): return dict(offers=self.offers, unit_atoms=self.unit_atoms, time_limited_offers=self.time_limited, phase_limited_offers=self.phase_limited, slack_rejected=self.slack_rejected, retention_seconds=self.spent, time_cap_s=self.time_cap_s, phase_share=self.phase_share)
