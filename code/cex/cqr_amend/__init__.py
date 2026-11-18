"""VERIFICATION AMENDMENT tooling (A1 review, 18 Nov 2026): re-verify the IMMUTABLE outcomes of a completed shard with a SEPARATELY REVIEWED verifier identity while binding the ORIGINAL
producer identity. Outside every candidate inventory scope (cex/cqr_amend is in no registry scope); imports the verifier build's checker / gate helpers read-only; never modifies the original
run directory; never relabels original workers; never weakens an identity check (the producer scope is compared with the ORIGINAL frozen inventory, the verifier scope with the current build)."""
AMEND_VERSION = 'cqr-verification-amendment-v1 (2026-11-18)'
