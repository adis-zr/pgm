# Library and research layout

All supported implementations belong to one installed package, `pgm`. Research
code depends on that package; the package does not depend on research code.

| Path | Responsibility |
|---|---|
| `src/pgm/api.py`, `contracts.py` | Public UAI inference request/result contract |
| `src/pgm/switchboard.py`, `policies/`, `planning/` | Admission and scheduling of representation-compatible backends |
| `src/pgm/registry.py` | One registry for automatic backend loading and explicit method access |
| `src/pgm/backends/` | Process-isolated UAI adapters and shared worker boundary |
| `src/pgm/runtime/`, `validation/` | Resource ownership, validation, native setup and publication |
| `src/pgm/algorithms/{structural,block,quotient,response}` | Existing general inference implementations |
| `src/pgm/algorithms/{cqr,cbi,sf,h4}` | Packaged specialist implementations |
| `src/pgm/specialists/` | Stable explicit specialist interfaces; direct canonical imports |
| `research/campaigns/` | Experimental runners, generators, controls, analyzers and packagers |
| `research/archive/` | Historical snapshots and artifacts with preserved bytes |
| `research/comparators/` | Historical third-party integrations |
| `benchmarks/external/` | Current external inputs, comparator sources and benchmark/replay tooling |
| `tests/`, `tests/qualification/` | Current tests and enforcing installation qualification |

There is no `code/` tree, top-level specialist package alias, or runtime
`sys.path` bridge. The wheel discovers only `pgm.*` under `src`. Host-built
libraries and records go to the configured or per-user cache; builds do not
modify the installed/source package. H4's optional GMP/MPFR dependencies are
documented separately from the general kernels.

`pgm.infer` keeps the existing UAI singleton contract and policies. `accepted`
remains the default. `pgm.method(name)` resolves a lazy provider with immutable
capability metadata and delegates to its existing native API. For example,
`pgm.method("cbi").solve` and `.verify` are the CBI solver and checker. The
switchboard's method resolver and UAI worker use this same registry.

This does not manufacture representation conversions. CBI needs a supplied
product-kernel block model, SF a supplied sparse two-block law, CQR its finite
query language, and H4 its fixed arithmetic cohort. The registry distinguishes
these from the four generic UAI backends; attempts to schedule a specialist as
a generic UAI backend are rejected. Their result types and guarantees are not
silently translated into the singleton contract.

Historical commands tied to old paths are reproduced at their original commits.
`benchmarks/external/replay_frozen.py` restores those source identities in an
isolated worktree and retains the original analyzer checks. Current experiments
use canonical imports and the explicit optional records root.
