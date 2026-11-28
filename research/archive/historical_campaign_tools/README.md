# Frozen-protocol campaign tools

`run_revision.py` and `validate_round.py` are retained byte-identically from the
migration baseline. They describe historical source layouts, pinned reference
commits, invocation policies, and source-identity criteria. Reproduce their rounds
from the original packet's frozen code and harness; the current layout does not
substitute new module paths into those historical comparisons.

The corresponding current campaign entry points refuse with
`HISTORICAL_PROTOCOL_ONLY` and produce no result or validation record. This prevents
a missing old path from turning an empty git diff into a false preservation claim.
All mathematical implementations remain in the canonical package.
