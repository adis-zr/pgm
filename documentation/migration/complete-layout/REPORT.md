# Complete layout migration — qualified review branch

The physical migration is complete. `code/` is absent. All supported methods
are package-owned under `src/pgm`; experiments and preserved history are under
`research`. Current benchmark tools and tests have their own directories.
The available qualification passes, and the independent review approves the
implementation. Main has not been changed by this work.

Implementation: `63513e043e93f20fe3a23e9166fff09bc86c1926`.
Published prerequisite: `7c67a3544afca74587ac066612a60b79c7aabdec`.
The subsequent commit contains documentation and evidence only.

## What changed

| Location | Contents |
|---|---|
| `src/pgm/algorithms` | structural, block, quotient, response, CQR, CBI, SF and H4 implementations and native sources |
| `src/pgm/specialists`, `registry.py` | Explicit specialist interfaces and shared lazy method registry |
| `research/campaigns` | Experimental controls, generators, runners and analysis |
| `research/archive` | Byte-preserved historical implementations, native artifacts and retired tools |
| `research/comparators` | Retained historical integrations |
| `benchmarks/external` | Current external suite, comparator sources and benchmark/replay tools |
| `tests`, `tests/qualification` | Current tests and enforcing wheel/installation qualification |

`pgm.infer` retains its contract. Accepted is still the default; automatic is
opt-in. The same four UAI backends remain automatically selectable. The shared
registry also exposes `pgm.method("cqr")`, `pgm.method("cbi")`,
`pgm.method("sf")` and `pgm.method("h4")`. Those methods retain their own input
representations, result types and checkers. This migration does not manufacture
generic UAI conversions or claim H4 is a generic graph recognizer.

Production has no legacy path bridge, top-level specialist aliases, research
imports or `sys.path` mutations. The wheel contains only the `pgm` package and
its distribution metadata, with native source but no host binaries. Native
builds use an explicit or per-user external cache and do not modify source or
installed package files. H4's optional builder records source/compiler identity
and rejects unsuccessful numerical probes even when their process exits zero.

Research subprocesses now bind imports to the checkout named by their source
argument. Before/after probes cannot silently load this checkout while reporting
a different one. Manifest generation rejects foreign-root labels for local
in-process generators; current native provenance is checked against source and
binary hashes. Frozen-protocol tools that cannot validly reinterpret a new
layout refuse explicitly and retain their original source in the archive.

## Preservation evidence

The machine-checked map accounts for **485/485** old `code/` files exactly once,
with **499 total dispositions** including other displaced tools. It verifies
**175 byte-preserved archived files**, **8 preserved historical probe/protocol
copies**, and **47 wrappers replaced by their original canonical targets**.
Only two empty namespace/placeholder files lack a destination.

Independent review checked **74 protected production files** against the
published prerequisite: the four general engines, policies, exact input and
publication boundaries, public contract and attempt/cleanup implementation are
byte-identical. It also checked **90 historical evidence files** unchanged.
The moved specialist mathematics has import-only/placement edits, independently
checked tiny truth cases, and installed-wheel execution evidence.

## Qualification at the frozen implementation

| Check | Result |
|---|---|
| Full serial test suite | 369 passed, 47 subtests passed; 6 private-fixture instances blocked |
| Same-host parity vs clean prerequisite | IDENTICAL |
| DGP10 controls | 12/12 |
| DGP10 numerical oracle | PASS |
| Inherited D1–D90 | 39 portable passed, 51 private-record dependencies blocked, 0 unexpected failures |
| HP / unified / scheduling controls | 80/80, 57/57, 32/32 |
| Strict fresh-wheel relocation | PASS, all required probes |
| Installed specialist checks | CBI/SF solve-and-check; CQR finite queries and normalizer; H4 four native roles and C/PI/PP checks |
| Package/native ownership | Correct installed origins, external caches, unchanged installed source |
| libDAI comparator qualification | 11/11 |
| Historical benchmark replay | 732 cells, 122 input bindings, 3 reference bindings; reports byte-identical |
| Independent source/evidence review | PASS / APPROVE |

The final wheel is SHA256
`de14d89cac6b6a137075a14d1a41bb9a9fbda84f418203d0fa086194db2134f3`. Its 138 package entries were independently compared with
the frozen source. See QUALIFICATION.json, SUPPLEMENT.json, INDEPENDENT_REVIEW.json,
and the raw evidence archive for exact commands, results and identities.

The public H4 witness and new migration tests do not substitute for the six
private specialist fixtures or the 51 private inherited controls. Those remain
blocked until their original inputs are supplied through the documented roots.

## Disclosures and limits

An initial development test run used cold native caches: two route assertions
failed although answers were correct. Explicit native setup repaired the test
environment; qualification now requires that setup before route checks. The
first development wheel build lacked its build backend; that failed setup log
is retained. The first full frozen qualification lacked `mpmath`, so only the
numerical oracle failed. Installing this qualification-only dependency and
repeating the complete serial qualification on the same clean implementation
passed. No engine or tolerance changed in response to these failures.

Historical full campaigns still require their original commits and inputs.
In particular, the old scheduling-revision runner, packet validator, DGP10
packet-layout probe and CQR full multi-arm matrix are not claimed as newly
qualified scientific protocols. The packaged methods and current qualified
entrypoints are separate from those historical campaign contracts.

No new performance campaign ran here. The 732-cell result is an exact replay of
the published evidence: automatic 52/61 in both repeats, accepted 40/61; five
automatic-versus-accepted cost flags and the 1qt9 partial-coordinate loss remain.
Automatic/JT median ratio 8.389 on 31 mutual completions still does not establish
broad speed dominance. All 61 inputs remain exposed regression inputs. A new
performance round must freeze its own full external-suite experiment.

## Reproduction and handoff

The qualification recipe and required test dependencies, including `mpmath`,
are in README.md in this directory. The raw archive preserves both full
qualification attempts, development failures, independent checks, tested wheels,
native build records and the frozen benchmark replay. EVIDENCE_IDENTITY.json
binds its bytes. The distribution packet adds the Git bundle and guarded Claude
application instructions. No remote push or main promotion was performed.
