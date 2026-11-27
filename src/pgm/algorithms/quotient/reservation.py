"""DGP10 shared RESERVATION TRANSACTION (DGP9 independent review F9-2 / F9-3; carried repair contract section 1; FROZEN_EXPERIMENT_SPEC section 3 item 1). An adapter over the accepted `coarse_envelope.Budget` charge / release
interface (the accepted implementation is NOT replaced: compatibility with every untouched caller) that gives every reservation an IDENTITY (a token with a nonnegative byte charge, a label and a state) and enforces the state model
    UNRESERVED -> TXN_OWNED -> OWNER_OWNED -> CLOSED
inside one constructor: a `Txn` records every token it acquires; ANY exception leaving the `with` block rolls back every token still owned by the transaction (reverse order) and re-raises -- the budget's live charge returns EXACTLY to
its entry value plus whatever was explicitly transferred (nothing, when the constructor failed before returning an owner); a successful construction TRANSFERS the retained tokens to the returned `Owner` (explicitly, one by one),
and temporary tokens still transaction-owned at normal exit are released there (so a temporary can never outlive its constructor). `Owner.close()` is idempotent (every token released once); releasing or transferring a token twice,
releasing a token through the wrong holder, or a release that would drive the budget below zero is an INVARIANT FAILURE (`coarse_envelope.Defect`), never a clamp to zero. `Txn.adopt(owner)` makes an already-returned owner part of
the transaction's failure scope (the sequential two-plan construction: a failed second plan closes the first inside the constructor). `Txn.live_delta()` reports the live change since entry for the controls. Garbage collection and
destructors are never part of the protocol."""
from pgm.algorithms.quotient import coarse_envelope as CE


class Token:
    __slots__ = ('bytes', 'what', 'state', 'holder')
    def __init__(self, n, what): self.bytes = int(n); self.what = what; self.state = 'TXN'; self.holder = None
    def record(self): return dict(bytes=self.bytes, what=self.what, state=self.state)


class Owner:
    """the explicit charge owner of a constructed object: holds OWNER_OWNED tokens; `close()` releases them once (idempotent); `bytes` = the total still owned"""
    def __init__(self, budget, tag=''):
        self.budget = budget; self.tag = tag; self.tokens = []; self.closed = False
    @property
    def bytes(self): return sum(t.bytes for t in self.tokens if t.state == 'OWNER')
    def close(self):
        """release every owned token exactly once; a second close is a no-op"""
        if self.closed: return 0
        n = 0
        for t in self.tokens:
            if t.state == 'OWNER': n += _release_token(self.budget, t)
        self.closed = True; return n
    def record(self): return dict(tag=self.tag, bytes=self.bytes, tokens=[t.record() for t in self.tokens], closed=self.closed)


def _release_token(budget, t):
    if t.state == 'CLOSED': raise CE.Defect('reservation %r released twice' % t.what)
    if budget is not None:
        if t.bytes > budget.live: raise CE.Defect('reservation ledger underflow: releasing %d B (%s) with %d B live' % (t.bytes, t.what, budget.live))
        budget.release(t.bytes)
    t.state = 'CLOSED'; return t.bytes


class Txn:
    """one constructor's reservation transaction (a context manager); `budget` may be None (every operation is then a no-op on the ledger but the ownership protocol still runs)"""
    def __init__(self, budget, clock=None, tag=''):
        self.budget = budget; self.clock = clock; self.tag = tag; self.tokens = []; self.adopted = []; self.entry_live = (budget.live if budget is not None else 0); self.transferred = 0; self.rolled_back = None; self.closed = False
    def __enter__(self): return self
    def reserve(self, n, what):
        """charge n bytes (typed MEMORY refusal from the budget when it does not fit; nothing of this transaction changes on refusal) -> a TXN_OWNED token"""
        if self.clock is not None: self.clock.poll('reservation: %s' % what)
        n = int(n)
        if n < 0: raise CE.Defect('negative reservation for %s' % what)
        if self.budget is not None: self.budget.charge(n, what)
        t = Token(n, what); self.tokens.append(t); return t
    def release(self, t):
        """an explicit early release of a TRANSACTION-owned temporary"""
        if t.state != 'TXN' or t not in self.tokens: raise CE.Defect('release of a token not owned by this transaction (%s, state %s)' % (t.what, t.state))
        n = _release_token(self.budget, t); self.tokens.remove(t); return n
    def transfer(self, t, owner):
        """ownership transfer of a TXN_OWNED token to the returned owner (no uncharged moment: the charge stays on the ledger throughout)"""
        if t.state != 'TXN' or t not in self.tokens: raise CE.Defect('transfer of a token not owned by this transaction (%s, state %s)' % (t.what, t.state))
        if owner.closed: raise CE.Defect('transfer to a closed owner (%s)' % owner.tag)
        t.state = 'OWNER'; t.holder = owner; owner.tokens.append(t); self.tokens.remove(t); self.transferred += t.bytes; return t
    def adopt(self, owner):
        """an already-constructed owner joins the failure scope: it is closed when this transaction rolls back"""
        self.adopted.append(owner); return owner
    def live_delta(self): return (self.budget.live - self.entry_live) if self.budget is not None else 0
    def __exit__(self, et, ev, tb):
        if self.closed: return False
        self.closed = True
        if et is not None:
            # ROLLBACK: every transaction-owned token in reverse order, then every adopted owner; the live charge returns to the entry value (+ nothing: adopted owners were constructed inside)
            freed = 0
            for t in reversed(self.tokens):
                if t.state == 'TXN': freed += _release_token(self.budget, t)
            self.tokens = []
            for o in reversed(self.adopted): freed += o.close()
            self.rolled_back = freed
            return False                                                      # re-raise
        # normal exit: temporaries still owned by the transaction are released here (a temporary never outlives its constructor)
        for t in reversed(self.tokens):
            if t.state == 'TXN': _release_token(self.budget, t)
        self.tokens = []
        return False
    def record(self): return dict(tag=self.tag, entry_live=self.entry_live, transferred=self.transferred, rolled_back=self.rolled_back, open_tokens=[t.record() for t in self.tokens])
