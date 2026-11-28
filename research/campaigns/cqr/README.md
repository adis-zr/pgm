# CQR research tools

The installable implementation is `pgm.algorithms.cqr`, exposed through
`pgm.specialists.cqr`. It retains the finite query language, including joint,
parity, conditional, bounded-table and normalizer tasks. It has no dependency on
this directory, the archived PAC implementation, or a source checkout.

Run these research commands from the repository root:

```sh
python -m research.campaigns.cqr.worker --help
python -m research.campaigns.cqr.references --help
python -m research.campaigns.cqr.acquire --help
```

`PGM_RECORDS_ROOT` selects the optional private record checkout. Research child
processes use the current interpreter and the explicit repository/package paths.
The full historical qualification suite is available as
`python -m research.campaigns.cqr.qualification`; it is an expensive research
campaign, not part of the short package migration tests.

`CQR_QUALIFICATION.json` is preserved historical evidence. It does not qualify the
new file layout. Every new campaign must freeze its new inventory; historical
scored records and their identities must not be relabelled. Source inventory
functions now hash the canonical runtime and relocated research files.

The comparison registry and verifier compose the byte-preserved PAC snapshot in
`research/archive/pac`. `_legacy.py` scopes its bare imports to a compatibility
context and restores the caller's import path and module bindings. This code is
research-only. Full historical baseline campaigns still require their declared
inputs, native binaries and environment; the migration does not claim those
campaigns were rerun.
