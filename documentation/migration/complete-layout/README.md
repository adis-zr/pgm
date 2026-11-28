# Complete layout migration

This is a source-layout and installation change from published commit
`7c67a3544afca74587ac066612a60b79c7aabdec`. It does not change inference
formulae, scheduling policies, benchmark cohorts, tolerances or the accepted default.

## Current organization

- `src/pgm`: every supported implementation, native source, public interface,
  common method registry, switchboard, resource boundary and checker.
- `research/campaigns`: experiment runners, generators, controls and analysis.
- `research/archive`: historical implementations and artifacts retained with
  their original bytes. Reproduction of old campaigns uses their pinned commits.
- `benchmarks/external`: external data, libDAI/PGMax integrations and current
  benchmark tooling.
- `tests`: current conformance, package, boundary and installation qualification.

There is no `code/` tree or production path bridge. See
[the architecture](../../architecture/LAYOUT.md) and
[the complete file map](MIGRATION.json). The map accounts for every one of the
485 previously tracked files below `code/`, plus displaced tools outside that tree.
Empty namespace/placeholder files are the only entries without a destination.
Retired compatibility wrappers resolve to their canonical implementation in the map.

The four UAI backends remain structural, block, quotient and response. CBI, SF,
CQR and H4 are packaged methods available through `pgm.method(name)` with their
native representations and checkers. This refactor does not claim automatic
conversion from arbitrary UAI models into those specialist representations.

Native compilation is explicit setup. Build products and generated records now
live in `PGM_NATIVE_CACHE` or the per-user cache, never in the package. H4 additionally
requires GMP/MPFR development libraries and is built by `python -m pgm.build --h4`.

## Historical protocol boundaries

The old scheduling-revision runner and DGP packet validator are retained with
their original bytes under `research/archive/historical_campaign_tools`.
Their current-path launchers refuse with `HISTORICAL_PROTOCOL_ONLY`; run those
protocols in their original checkout. The DGP10 old packet-layout probe likewise
refuses the new layout explicitly. Moving a file does not authorize reinterpreting
an old freeze against a new source tree.

The CQR full historical multi-arm matrix also requires its pinned baseline/native
artifacts and original checkout. Its packaged solver, independent checker and
current worker are qualified separately; no full legacy campaign is claimed here.

Before/after review probes bind their imports to the requested checkout. Current
DGP launchers bind the child interpreter to the declared source, and manifest
generation refuses a foreign root when it imports local generators. This prevents
source labels from silently describing a different installed package. None of
these plumbing repairs reruns or revises an old scored cell.

## Reproduce qualification

Use a clean checkout, Python 3.12, declared project dependencies, the `build`,
`setuptools`, `wheel`, `pytest` and `mpmath` tools (`mpmath` is only for the
DGP numerical oracle), qualified Clang `CC`/`CXX`, and the
optional H4 GMP/MPFR development dependencies. Run serially; do not run another
native qualification or benchmark at the same time.

```bash
python tests/qualification/verify_migration.py
export PGM_BASELINE_ROOT=/absolute/path/to/clean-7c67a35-checkout
export PGM_TEST_H4_NATIVE=1
sh tests/qualification/qualify.sh /path/to/python /path/to/build-python /new/scratch/path
```

Alternatively supply `PARITY_REFERENCE` pointing to a reference generated from
that baseline on the same host. The qualifier builds native kernels before timed
route controls, builds the wheel in a disposable source copy, installs it outside
the checkout, and exercises it under `python -I` with independent checker probes.
Private historical fixture controls remain explicitly blocked when their files
are absent; public tiny witnesses do not substitute for them.

## Evidence interpretation

The qualification report and raw receipts accompany the review commit. The
previous 732-cell external benchmark is replayed from its original frozen source,
not scored again by this migration. No new performance or unseen-evaluation claim
is made. The current 61 external tasks are all exposed regression inputs. The
published cost flags and partial-coordinate loss remain part of that evidence.
