"""SUCCESSOR VERIFICATION tooling (A1 review 18 Nov 2026; repair-2 review CQR-AF2-01/02, 19 Nov 2026): re-verify the IMMUTABLE outcomes of a completed shard with a SEPARATELY
identified VERIFIER build while binding the ORIGINAL PRODUCER identity and the ORIGINAL gate's complete receipt / output / dependency history. Outside every candidate inventory scope
(cex/cqr_amend is in no registry scope): its own identity (every file of this package + the supervisor module it requires) is pinned at preparation and ENFORCED at every later step
(a changed tool refuses against an old prepared identity, even for a comment). Imports the verifier build's gate / checker / report helpers read-only; never writes into the original run
directory; never relabels original workers; every attempt is an immutable directory; the gate -> report -> closeout successor chain is explicit (old producer / new verifier bindings)."""
AMEND_VERSION = 'cqr-successor-verification-v2 (2026-11-19; v1 2026-11-18 superseded: no planned/observed set equality, no historical authority, tool identity recorded but not enforced, outputs overwritten, no consumer chain)'
